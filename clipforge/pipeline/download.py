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
