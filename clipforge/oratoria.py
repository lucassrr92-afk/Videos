"""Treino de oratória: serve a página e gera feedback de coach com o Claude a partir da transcrição."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config

router = APIRouter()
PAGE = config.ROOT / "oratoria" / "index.html"

MODES = {
    "improviso": "improviso sobre um tema surpresa",
    "tema": "fala sobre um tema escolhido pela pessoa",
    "roteiro": "leitura de um roteiro com teleprompter",
    "pitch": "pitch de vendas / apresentação",
    "diccao": "exercício de dicção com trava-língua",
}

SYSTEM_PROMPT = """Você é um coach de oratória experiente e direto, que treina profissionais brasileiros.
Recebe a transcrição automática de um treino (pode ter erros de reconhecimento de voz: não critique
ortografia nem pontuação) e métricas medidas pelo app. Dê um feedback em português do Brasil, em texto
simples sem markdown pesado, com no máximo ~250 palavras, nesta estrutura:

PONTOS FORTES: 2 itens concretos, citando trechos da fala.
O QUE MELHORAR: 3 itens, do mais importante para o menos, cada um com um exemplo da fala e como reescrever.
ESTRUTURA: avalie abertura, desenvolvimento e fechamento em 1-2 frases.
VERSÃO MELHORADA: reescreva a abertura (1-2 frases) como um orador confiante diria.
DESAFIO PARA O PRÓXIMO TREINO: 1 exercício específico.

Seja encorajador, mas honesto. Não invente o que a pessoa não disse."""


class Practice(BaseModel):
    mode: str = "improviso"
    topic: str = ""
    dur: int = 0
    words: int = 0
    wpm: int | None = None
    fillers: int = 0
    fpm: float | None = None
    fillerList: dict[str, int] = Field(default_factory=dict)
    pauses: int = 0
    longestPause: float = 0
    volSd: float = 0
    score: int = 0
    transcript: str = Field("", max_length=20000)


@router.get("/oratoria")
def page():
    return FileResponse(PAGE, media_type="text/html")


MAX_AUDIO_MB = 60
# Pista para o Whisper manter hesitações e vícios ("é...", "tipo", "né"), que ele costuma apagar.
VERBATIM_PROMPT = "Então, é... tipo, eu acho que, né, hum, ahn, assim, basicamente a gente vai, tipo assim."


def _can_transcribe() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None and shutil.which("ffmpeg") is not None


@router.get("/api/oratoria/status")
def status():
    """Diz à página o que o servidor oferece: transcrição do áudio e feedback por IA."""
    return {"transcribe": _can_transcribe(), "ai": bool(config.ANTHROPIC_API_KEY)}


@router.post("/api/oratoria/transcribe")
def transcribe(file: UploadFile = File(...)):
    """Transcreve o áudio do treino. Usado no iPhone e em navegadores sem reconhecimento de voz."""
    if not _can_transcribe():
        raise HTTPException(503, "transcrição indisponível no servidor (faltam faster-whisper ou ffmpeg)")
    from .pipeline.transcribe import _get_model

    with tempfile.TemporaryDirectory() as tmp:
        src, wav = Path(tmp) / "fala.bin", Path(tmp) / "fala.wav"
        size = 0
        with src.open("wb") as out:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > MAX_AUDIO_MB << 20:
                    raise HTTPException(413, f"áudio maior que {MAX_AUDIO_MB} MB")
                out.write(chunk)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not wav.exists():
            raise HTTPException(400, "não consegui ler o áudio enviado")
        segments, info = _get_model().transcribe(str(wav), language="pt", word_timestamps=True,
                                                 initial_prompt=VERBATIM_PROMPT, condition_on_previous_text=False)
        words, parts = [], []
        for seg in segments:
            parts.append(seg.text.strip())
            words += [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                      for w in (seg.words or []) if w.word.strip()]
    return {"text": " ".join(p for p in parts if p), "words": words, "duration": info.duration}


@router.post("/api/oratoria/feedback")
def feedback(p: Practice):
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY não configurada no servidor")
    if not p.transcript.strip():
        raise HTTPException(400, "transcrição vazia")

    import anthropic

    vicios = ", ".join(f'"{k}" x{v}' for k, v in p.fillerList.items()) or "nenhum"
    user = (
        f"Modo: {MODES.get(p.mode, p.mode)}\n"
        f"Tema: {p.topic or '(não informado)'}\n"
        f"Duração: {p.dur}s · {p.words} palavras · ritmo: {p.wpm or '?'} palavras/min (ideal 120-160)\n"
        f"Vícios de linguagem: {p.fillers} ({p.fpm or '?'} por minuto) → {vicios}\n"
        f"Pausas longas (>2,5 s): {p.pauses}, a maior com {p.longestPause}s\n"
        + (f"Variação de volume: {p.volSd} dB (abaixo de 4 soa monótono)\n" if p.volSd else "")
        + f"Nota automática do app: {p.score}/100\n\n"
        f"<transcricao>\n{p.transcript}\n</transcricao>"
    )
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError as e:
        raise HTTPException(502, f"erro na API do Claude: {e}") from e
    if msg.stop_reason == "refusal":
        raise HTTPException(422, "O modelo recusou analisar esta fala.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return {"feedback": text}
