"""Renderização final de cada corte com ffmpeg.

Etapas (em um único filtergraph):
1. Jump cuts: remove silêncios longos usando os timestamps das palavras.
2. Enquadramento vertical 1080x1920:
   - "crop": segue o rosto (planos estáveis);
   - "blur": vídeo inteiro no centro sobre fundo desfocado (bom para telas, slides, jogos);
   - "auto": crop se houver rosto na maior parte do trecho, senão blur.
3. Leve "punch-in" (zoom de 8%) alternado a cada jump cut, dando dinamismo.
4. Legendas animadas + título de gancho (ASS).
5. Barra de progresso no rodapé.
6. Áudio normalizado para -14 LUFS (padrão das plataformas).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import config
from . import reframe, subtitles


def keep_intervals(words: list[dict], clip_len: float, max_silence: float = 0.55, pad: float = 0.12) -> list[tuple[float, float]]:
    """Intervalos (relativos ao corte) a manter, removendo silêncios > max_silence."""
    if not words:
        return [(0.0, clip_len)]
    spans: list[list[float]] = []
    for w in words:
        s, e = max(0.0, w["start"] - pad), min(clip_len, w["end"] + pad)
        if spans and s - spans[-1][1] <= max_silence:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    spans[0][0] = 0.0 if spans[0][0] < 0.6 else spans[0][0]
    spans[-1][1] = clip_len if clip_len - spans[-1][1] < 0.8 else spans[-1][1]
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a > 0.05]


def remap(t: float, intervals: list[tuple[float, float]]) -> float:
    """Converte tempo original (relativo ao corte) para o tempo após os jump cuts."""
    acc = 0.0
    for a, b in intervals:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


def _between_expr(intervals: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in intervals)


def _escape_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render_clip(
    source: str,
    clip: dict,
    words_abs: list[dict],
    out_path: Path,
    layout: str = "auto",
    jump_cuts: bool = True,
    caption_preset: str = "amarelo",
    font: str = "Inter Black",
    progress_bar: bool = True,
) -> dict:
    W, H, FPS = config.OUT_W, config.OUT_H, config.OUT_FPS
    start, end = float(clip["start"]), float(clip["end"])
    clip_len = end - start
    work = out_path.parent

    # Palavras relativas ao início do corte
    words = [{**w, "start": w["start"] - start, "end": w["end"] - start} for w in words_abs]

    intervals = keep_intervals(words, clip_len) if jump_cuts else [(0.0, clip_len)]
    final_len = sum(b - a for a, b in intervals)
    words_final = [{**w, "start": remap(w["start"], intervals), "end": remap(w["end"], intervals)} for w in words]

    ass = subtitles.build_ass(
        words_final, work / f"{out_path.stem}.ass", W, H,
        hook_title=clip.get("hook_title", ""), font=font, preset=caption_preset,
    )

    # --- Enquadramento ---
    analysis = reframe.analyze(source, start, end)
    src_w, src_h = analysis["src_w"], analysis["src_h"]
    mode = layout
    if layout == "auto":
        mode = "crop" if analysis["faces_ratio"] >= 0.5 and src_w / max(src_h, 1) > 1.2 else "blur"
    if src_w / max(src_h, 1) <= 9 / 16 + 0.01:
        mode = "fit"  # já é vertical

    sel = _between_expr(intervals)
    f: list[str] = [
        f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,fps={FPS}[v0]" if jump_cuts and len(intervals) > 1 else f"[0:v]fps={FPS}[v0]",
        f"[0:a]aselect='{sel}',asetpts=N/SR/TB[a0]" if jump_cuts and len(intervals) > 1 else "[0:a]anull[a0]",
    ]

    if mode == "crop":
        crop_w = int(src_h * 9 / 16) // 2 * 2
        # o crop roda ANTES do select (tempo original), por isso ajustamos a ordem:
        xexpr = reframe.crop_x_expression(analysis["shots"], src_w, crop_w)
        f[0] = f"[0:v]crop={crop_w}:{src_h}:'{xexpr}':0," + f[0][len("[0:v]"):]
        # punch-in alternado a cada jump cut
        if jump_cuts and len(intervals) > 1:
            cuts = []
            acc = 0.0
            for a, b in intervals:
                cuts.append(acc)
                acc += b - a
            zoom_terms = "+".join(
                f"between(t\\,{cuts[i]:.3f}\\,{(cuts[i+1] if i + 1 < len(cuts) else final_len + 1):.3f})"
                for i in range(1, len(cuts), 2)
            )
            f.append(
                f"[v0]scale=w='{W}*(1+0.08*({zoom_terms}))':h='{H}*(1+0.08*({zoom_terms}))':eval=frame,"
                f"crop={W}:{H},setsar=1[v1]"
            )
        else:
            f.append(f"[v0]scale={W}:{H},setsar=1[v1]")
    elif mode == "blur":
        f.append("[v0]split[bg][fg]")
        f.append(f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.12[bgb]")
        f.append(f"[fg]scale={W}:-2,setsar=1[fgs]")
        f.append("[bgb][fgs]overlay=(W-w)/2:(H-h)/2-80,setsar=1[v1]")
    else:
        f.append(f"[v0]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[v1]")

    fonts = _escape_path(config.FONTS_DIR)
    last = "v1"
    if progress_bar and final_len > 0:
        f.append(f"[v1]drawbox=x=0:y={H - 14}:w='{W}*t/{final_len:.3f}':h=14:color=white@0.85:t=fill[v2]")
        last = "v2"
    f.append(f"[{last}]ass='{_escape_path(ass)}':fontsdir='{fonts}',format=yuv420p[vout]")
    f.append("[a0]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")

    graph = work / f"{out_path.stem}.filter"
    graph.write_text(";\n".join(f))

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", source,
        "-filter_complex_script", str(graph),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {proc.stderr[-2000:]}")

    thumb = out_path.with_suffix(".jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(out_path), "-frames:v", "1", "-q:v", "3", str(thumb)],
        check=False,
    )
    return {"path": str(out_path), "thumb": str(thumb), "duration": round(final_len, 2), "layout": mode}
