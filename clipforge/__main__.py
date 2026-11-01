"""Uso:
  python -m clipforge serve                      # interface web em http://localhost:8000
  python -m clipforge URL [--clips 5] [--publish youtube,tiktok,instagram]
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from .app import main as serve

        serve()
        return

    ap = argparse.ArgumentParser(prog="clipforge")
    ap.add_argument("url")
    ap.add_argument("--clips", type=int, default=5)
    ap.add_argument("--min-len", type=int, default=20)
    ap.add_argument("--max-len", type=int, default=60)
    ap.add_argument("--layout", choices=["auto", "crop", "blur"], default="auto")
    ap.add_argument("--no-jump-cuts", action="store_true")
    ap.add_argument("--caption", default="amarelo", choices=["amarelo", "verde", "rosa", "branco"])
    ap.add_argument("--publish", default="", help="lista separada por vírgula: youtube,tiktok,instagram")
    a = ap.parse_args()

    from . import jobs

    platforms = [p for p in a.publish.split(",") if p]
    opts = {
        "clips": a.clips, "min_len": a.min_len, "max_len": a.max_len, "layout": a.layout,
        "jump_cuts": not a.no_jump_cuts, "caption_preset": a.caption,
        "platforms": platforms, "auto_publish": bool(platforms),
    }
    job = jobs.create(a.url, opts)
    jobs._executor.shutdown(wait=True)  # aguarda terminar
    job = jobs.load(job["id"])
    print(json.dumps({k: job[k] for k in ("id", "status", "error", "clips")}, ensure_ascii=False, indent=2))
    print(f"\nArquivos em: {jobs.job_dir(job['id'])}")


if __name__ == "__main__":
    main()
