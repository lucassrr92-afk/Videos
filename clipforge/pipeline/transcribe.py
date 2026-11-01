"""Transcrição com timestamps por palavra (faster-whisper)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import config

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        device = config.WHISPER_DEVICE
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        compute = "float16" if device == "cuda" else "int8"
        _model = WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute)
    return _model


def extract_audio(video: Path, wav: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )
    return wav


def transcribe(video: Path, work_dir: Path, progress=None) -> dict:
    """Retorna {language, segments:[{start,end,text,words:[{start,end,word}]}]}.

    O resultado é cacheado em work_dir/transcript.json.
    """
    cache = work_dir / "transcript.json"
    if cache.exists():
        return json.loads(cache.read_text())

    wav = extract_audio(video, work_dir / "audio.wav")
    model = _get_model()
    segments_iter, info = model.transcribe(
        str(wav),
        language=config.WHISPER_LANGUAGE,
        word_timestamps=True,
        vad_filter=True,
    )
    segments = []
    for seg in segments_iter:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
            for w in (seg.words or [])
            if w.word.strip()
        ]
        segments.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(), "words": words})
        if progress and info.duration:
            progress(min(seg.end / info.duration, 1.0))

    result = {"language": info.language, "duration": info.duration, "segments": segments}
    cache.write_text(json.dumps(result, ensure_ascii=False))
    wav.unlink(missing_ok=True)
    return result


def words_in_range(transcript: dict, start: float, end: float) -> list[dict]:
    out = []
    for seg in transcript["segments"]:
        if seg["end"] < start or seg["start"] > end:
            continue
        for w in seg["words"]:
            if w["start"] >= start - 0.05 and w["end"] <= end + 0.05:
                out.append(w)
    return out
