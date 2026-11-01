"""Orquestração: link do YouTube -> cortes editados -> publicação."""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .pipeline import download, highlights, render, transcribe
from .publishers import instagram, tiktok, youtube

log = logging.getLogger(__name__)
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1)  # um vídeo por vez (CPU/GPU pesados)

DEFAULT_OPTIONS = {
    "clips": 5,
    "min_len": 20,
    "max_len": 60,
    "layout": "auto",          # auto | crop | blur
    "jump_cuts": True,
    "caption_preset": "amarelo",
    "font": "Inter Black",
    "platforms": [],           # youtube | tiktok | instagram
    "auto_publish": False,     # True = posta sem revisão
}


def job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def load(job_id: str) -> dict:
    return json.loads((job_dir(job_id) / "job.json").read_text())


def save(job: dict) -> None:
    with _lock:
        p = job_dir(job["id"]) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2))
        tmp.replace(p)


def list_jobs() -> list[dict]:
    jobs = []
    for d in config.JOBS_DIR.iterdir():
        f = d / "job.json"
        if f.exists():
            try:
                jobs.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                pass
    return sorted(jobs, key=lambda j: j["created_at"], reverse=True)


def create(url: str, options: dict | None = None) -> dict:
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    job_dir(job_id).mkdir(parents=True)
    job = {
        "id": job_id,
        "url": url,
        "options": {**DEFAULT_OPTIONS, **(options or {})},
        "status": "na fila",
        "stage": "",
        "progress": 0.0,
        "error": None,
        "meta": {},
        "clips": [],
        "created_at": time.time(),
    }
    save(job)
    _executor.submit(run, job_id)
    return job


def _set(job: dict, **kw) -> None:
    job.update(kw)
    save(job)


def run(job_id: str) -> None:
    job = load(job_id)
    d = job_dir(job_id)
    opts = job["options"]
    try:
        _set(job, status="processando", stage="Baixando vídeo", progress=0.0)
        meta = download.download(job["url"], d, progress=lambda p: _set(job, progress=p * 0.15))
        _set(job, meta=meta, stage="Transcrevendo áudio", progress=0.15)

        tr = transcribe.transcribe(Path(meta["path"]), d, progress=lambda p: _set(job, progress=0.15 + p * 0.35))
        _set(job, stage="Escolhendo os melhores momentos", progress=0.5)

        picks = highlights.pick_highlights(tr, meta, n=int(opts["clips"]), min_len=int(opts["min_len"]), max_len=int(opts["max_len"]))
        if not picks:
            raise RuntimeError("Não encontrei trechos com fala suficiente para gerar cortes.")
        clips = []
        for i, c in enumerate(picks, 1):
            caption = c["caption"].strip()
            tags = " ".join(f"#{h}" for h in c["hashtags"])
            clips.append({
                "n": i, **c,
                "post_text": f"{caption}\n\n{tags}".strip(),
                "status": "na fila", "file": None, "thumb": None, "published": {},
            })
        _set(job, clips=clips, stage="Editando cortes", progress=0.55)

        for i, clip in enumerate(job["clips"]):
            _set(job, stage=f"Editando corte {i + 1}/{len(job['clips'])}")
            clip["status"] = "renderizando"
            save(job)
            words = transcribe.words_in_range(tr, clip["start"], clip["end"])
            try:
                res = render.render_clip(
                    meta["path"], clip, words, d / f"corte_{clip['n']:02d}.mp4",
                    layout=opts["layout"], jump_cuts=bool(opts["jump_cuts"]),
                    caption_preset=opts["caption_preset"], font=opts["font"],
                )
                clip.update(file=Path(res["path"]).name, thumb=Path(res["thumb"]).name,
                            final_duration=res["duration"], layout=res["layout"], status="pronto")
            except Exception as e:  # noqa: BLE001
                clip.update(status="erro", error=str(e)[-500:])
            _set(job, progress=0.55 + 0.4 * (i + 1) / len(job["clips"]))

        if opts.get("auto_publish") and opts.get("platforms"):
            _set(job, stage="Publicando")
            for clip in job["clips"]:
                if clip["status"] == "pronto":
                    publish_clip(job, clip["n"], opts["platforms"])

        _set(job, status="concluído", stage="Pronto", progress=1.0)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s falhou", job_id)
        _set(job, status="erro", error=f"{e}\n{traceback.format_exc()[-1500:]}")


def publish_clip(job: dict, n: int, platforms: list[str]) -> dict:
    clip = next(c for c in job["clips"] if c["n"] == n)
    path = str(job_dir(job["id"]) / clip["file"])
    results = clip.setdefault("published", {})
    for p in platforms:
        if results.get(p, {}).get("ok"):
            continue
        results[p] = {"ok": False, "status": "enviando"}
        save(job)
        try:
            if p == "youtube":
                r = youtube.upload(path, clip["post_title"], clip["post_text"], clip.get("hashtags", []))
            elif p == "tiktok":
                r = tiktok.upload(path, clip["post_text"])
            elif p == "instagram":
                r = instagram.upload(path, clip["post_text"])
            else:
                raise ValueError(f"plataforma desconhecida: {p}")
            results[p] = {"ok": True, **r}
        except Exception as e:  # noqa: BLE001
            results[p] = {"ok": False, "error": str(e)[:800]}
        save(job)
    return results


def publish_async(job_id: str, n: int, platforms: list[str]) -> None:
    def _go():
        publish_clip(load(job_id), n, platforms)

    threading.Thread(target=_go, daemon=True).start()


def update_clip(job_id: str, n: int, fields: dict) -> dict:
    job = load(job_id)
    clip = next(c for c in job["clips"] if c["n"] == n)
    for k in ("post_title", "post_text"):
        if k in fields:
            clip[k] = fields[k]
    save(job)
    return clip


def connections() -> dict:
    return {
        "youtube": youtube.is_connected(),
        "tiktok": tiktok.is_connected(),
        "instagram": instagram.is_connected(),
        "claude": bool(config.ANTHROPIC_API_KEY),
    }
