"""Escolha dos melhores momentos para cortes virais.

Usa o Claude (se ANTHROPIC_API_KEY estiver definido) para ler a transcrição e
escolher trechos com gancho forte, além de gerar título de gancho, legenda do
post e hashtags. Sem chave, cai numa heurística simples.
"""
from __future__ import annotations

import json
import logging
import re

from .. import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um editor de vídeos curtos (YouTube Shorts, TikTok, Instagram Reels) \
especialista em retenção. Recebe a transcrição com timestamps de um vídeo longo e escolhe os \
trechos com maior potencial viral para virarem cortes independentes.

Um bom corte:
- começa com um gancho forte nos primeiros 2 segundos (frase polêmica, pergunta, promessa, número, emoção);
- é compreensível sem o resto do vídeo (não começa no meio de um raciocínio nem depende de contexto anterior);
- termina numa conclusão, punchline ou frase de impacto, nunca no meio de uma frase;
- tem uma única ideia central.

Use exatamente os timestamps da transcrição para início e fim (início de uma fala, fim de outra). \
Os cortes não devem se sobrepor. Escreva títulos, legendas e hashtags no mesmo idioma do vídeo."""

CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "início em segundos"},
                    "end": {"type": "number", "description": "fim em segundos"},
                    "hook_title": {"type": "string", "description": "texto curto (máx. 6 palavras) exibido no topo do vídeo nos primeiros segundos"},
                    "post_title": {"type": "string", "description": "título do post (máx. 90 caracteres)"},
                    "caption": {"type": "string", "description": "legenda/descrição do post, 1-3 frases com CTA"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "viral_score": {"type": "integer", "description": "0 a 100"},
                    "reason": {"type": "string"},
                },
                "required": ["start", "end", "hook_title", "post_title", "caption", "hashtags", "viral_score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def _transcript_text(transcript: dict) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"])


def _claude_pick(transcript: dict, meta: dict, n: int, min_len: int, max_len: int) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    user = (
        f"Título do vídeo: {meta.get('title', '')}\n"
        f"Canal: {meta.get('channel', '')}\n"
        f"Duração: {transcript.get('duration', 0):.0f}s\n\n"
        f"Escolha até {n} cortes, cada um entre {min_len} e {max_len} segundos, ordenados do mais forte "
        f"para o mais fraco.\n\n<transcricao>\n{_transcript_text(transcript)}\n</transcricao>"
    )
    with client.beta.messages.stream(
        model=config.CLAUDE_MODEL,
        max_tokens=32000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": CLIP_SCHEMA}},
        # Se o pedido for recusado por um classificador, o servidor tenta outro modelo automaticamente.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError("O modelo recusou a análise deste vídeo.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Resposta truncada (max_tokens).")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)["clips"]


def _heuristic_pick(transcript: dict, n: int, min_len: int, max_len: int) -> list[dict]:
    """Sem IA: janelas de fala densa, preferindo frases com ?, ! e números."""
    segs = transcript["segments"]
    candidates = []
    for i, s in enumerate(segs):
        start, j, text = s["start"], i, []
        while j < len(segs) and segs[j]["end"] - start <= max_len:
            text.append(segs[j]["text"])
            j += 1
        if j == i:
            continue
        end = segs[j - 1]["end"]
        if end - start < min_len:
            continue
        joined = " ".join(text)
        words = len(joined.split())
        score = words / (end - start) * 10
        score += 8 * len(re.findall(r"[?!]", joined)) + 4 * len(re.findall(r"\d+", joined))
        first = s["text"]
        score += 15 if first.endswith("?") or re.search(r"\b(nunca|ninguém|segredo|verdade|maior|pior|melhor|never|secret|truth)\b", first, re.I) else 0
        candidates.append((score, start, end, first))
    candidates.sort(reverse=True)
    picked: list[dict] = []
    for score, start, end, first in candidates:
        if any(not (end <= p["start"] or start >= p["end"]) for p in picked):
            continue
        hook = " ".join(first.split()[:6]).rstrip(".,;:")
        picked.append({
            "start": start, "end": end, "hook_title": hook, "post_title": first[:90],
            "caption": first, "hashtags": ["shorts", "viral", "cortes"],
            "viral_score": int(min(score, 100)), "reason": "heurística",
        })
        if len(picked) >= n:
            break
    return picked


def _snap(clip: dict, transcript: dict, duration: float) -> dict:
    """Ajusta início/fim para não cortar palavras no meio."""
    words = [w for s in transcript["segments"] for w in s["words"]]
    if words:
        start_w = min(words, key=lambda w: abs(w["start"] - clip["start"]))
        end_w = min(words, key=lambda w: abs(w["end"] - clip["end"]))
        clip["start"] = max(0.0, start_w["start"] - 0.15)
        clip["end"] = min(duration or end_w["end"] + 0.4, end_w["end"] + 0.4)
    return clip


def pick_highlights(transcript: dict, meta: dict, n: int = 5, min_len: int = 20, max_len: int = 60) -> list[dict]:
    clips: list[dict] = []
    if config.ANTHROPIC_API_KEY and transcript["segments"]:
        try:
            clips = _claude_pick(transcript, meta, n, min_len, max_len)
        except Exception as e:  # noqa: BLE001
            log.warning("Falha ao usar Claude (%s); usando heurística.", e)
    if not clips:
        clips = _heuristic_pick(transcript, n, min_len, max_len)

    duration = transcript.get("duration") or meta.get("duration") or 0
    out = []
    for c in clips:
        c = _snap(c, transcript, duration)
        if c["end"] - c["start"] < 3:
            continue
        c["hashtags"] = [h.lstrip("#").replace(" ", "") for h in c.get("hashtags", []) if h.strip()]
        out.append(c)
    return out[:n]
