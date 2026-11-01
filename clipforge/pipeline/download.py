"""Download do vídeo do YouTube com yt-dlp."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yt_dlp


def download(url: str, out_dir: Path, progress: Callable[[float], None] | None = None) -> dict:
    """Baixa o vídeo (até 1080p) em MP4. Retorna {path, title, duration, channel}."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(min(d.get("downloaded_bytes", 0) / total, 1.0))

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    path = next(out_dir.glob("source.mp4"), None) or next(out_dir.glob("source.*"))
    return {
        "path": str(path),
        "title": info.get("title", ""),
        "duration": float(info.get("duration") or 0),
        "channel": info.get("uploader") or info.get("channel") or "",
        "description": (info.get("description") or "")[:2000],
    }


def http_get(url: str, dest: Path, progress: Callable[[float], None] | None = None) -> Path:
    """Baixa um arquivo por HTTP em streaming."""
    import requests

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1024 * 1024):
                fh.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0))
    return dest


def probe_local(path: Path, title: str = "") -> dict:
    """Valida um arquivo de vídeo enviado (trilhas de vídeo e áudio) com ffprobe."""
    import json
    import subprocess

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    info = json.loads(probe.stdout or "{}")
    kinds = {s.get("codec_type") for s in info.get("streams", [])}
    if probe.returncode != 0 or "video" not in kinds:
        raise RuntimeError("Arquivo inválido: não encontrei uma trilha de vídeo.")
    if "audio" not in kinds:
        raise RuntimeError("O vídeo não tem áudio; não dá para gerar legendas e escolher cortes.")
    return {"path": str(path), "title": title, "duration": float(info.get("format", {}).get("duration") or 0),
            "channel": "", "description": ""}


def download_url(url: str, out_dir: Path, title: str = "", progress: Callable[[float], None] | None = None) -> dict:
    """Baixa um arquivo de vídeo por URL direta e valida."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return probe_local(http_get(url, out_dir / "source.mp4", progress), title)
