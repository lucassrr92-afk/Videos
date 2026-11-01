"""Servidor web: cole o link, acompanhe a edição, revise e publique."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, jobs
from .publishers import tiktok, youtube

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="ClipForge")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class NewJob(BaseModel):
    url: str
    clips: int = 5
    min_len: int = 20
    max_len: int = 60
    layout: str = "auto"
    jump_cuts: bool = True
    caption_preset: str = "amarelo"
    platforms: list[str] = []
    auto_publish: bool = False


class ClipEdit(BaseModel):
    post_title: str | None = None
    post_text: str | None = None


class PublishReq(BaseModel):
    platforms: list[str]


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"conn": jobs.connections()})


@app.get("/api/connections")
def api_connections():
    return jobs.connections()


@app.post("/api/jobs")
def api_create(body: NewJob):
    if "youtu" not in body.url:
        raise HTTPException(400, "Envie um link do YouTube")
    opts = body.model_dump(exclude={"url"})
    return jobs.create(body.url.strip(), opts)


@app.get("/api/jobs")
def api_list():
    return jobs.list_jobs()


@app.get("/api/jobs/{job_id}")
def api_get(job_id: str):
    try:
        return jobs.load(job_id)
    except FileNotFoundError:
        raise HTTPException(404)


@app.patch("/api/jobs/{job_id}/clips/{n}")
def api_edit(job_id: str, n: int, body: ClipEdit):
    return jobs.update_clip(job_id, n, body.model_dump(exclude_none=True))


@app.post("/api/jobs/{job_id}/clips/{n}/publish")
def api_publish(job_id: str, n: int, body: PublishReq):
    jobs.publish_async(job_id, n, body.platforms)
    return {"ok": True}


@app.get("/media/{job_id}/{name}")
def media(job_id: str, name: str):
    if "/" in name or ".." in name or "/" in job_id or ".." in job_id:
        raise HTTPException(400)
    p = jobs.job_dir(job_id) / name
    if not p.exists() or p.suffix not in (".mp4", ".jpg"):
        raise HTTPException(404)
    return FileResponse(p)


# ---------- OAuth ----------
@app.get("/auth/youtube")
def auth_youtube():
    return RedirectResponse(youtube.auth_url())


@app.get("/auth/youtube/callback")
def auth_youtube_cb(request: Request):
    youtube.handle_callback(str(request.url))
    return RedirectResponse("/")


@app.get("/auth/tiktok")
def auth_tiktok():
    return RedirectResponse(tiktok.auth_url())


@app.get("/auth/tiktok/callback")
def auth_tiktok_cb(code: str, state: str):
    tiktok.handle_callback(code, state)
    return RedirectResponse("/")


def main():
    import uvicorn

    host_port = config.PUBLIC_BASE_URL.rsplit(":", 1)
    port = int(host_port[1]) if len(host_port) == 2 and host_port[1].isdigit() else 8000
    uvicorn.run("clipforge.app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
