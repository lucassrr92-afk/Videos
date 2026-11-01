"""Servidor web pessoal: envie o vídeo (ou um link), acompanhe a edição, revise e publique."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, jobs
from .publishers import tiktok, youtube

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="ClipForge")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
COOKIE = "cf_session"


# ---------- acesso por senha (uso pessoal) ----------
def _session_value() -> str:
    return hmac.new(config.APP_PASSWORD.encode(), b"clipforge-session", hashlib.sha256).hexdigest()


@app.middleware("http")
async def require_password(request: Request, call_next):
    if not config.APP_PASSWORD or request.url.path in ("/login", "/favicon.ico"):
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), _session_value()):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "não autenticado"}, status_code=401)
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(erro: int = 0):
    msg = "<p style='color:#ff5c5c'>Senha incorreta.</p>" if erro else ""
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>ClipForge</title><body style="background:#0e0f13;color:#eee;font-family:Inter,system-ui;display:grid;place-items:center;height:100vh;margin:0">
<form method=post style="background:#171920;padding:28px;border-radius:14px;border:1px solid #262a35;display:grid;gap:12px;width:280px">
<h2 style="margin:0">Clip<span style="color:#ffd400">Forge</span></h2>{msg}
<input type=password name=password placeholder="Senha" autofocus required style="padding:10px;border-radius:8px;border:1px solid #262a35;background:#0e0f13;color:#fff">
<button style="padding:10px;border:0;border-radius:8px;background:#ffd400;font-weight:700">Entrar</button></form>"""


@app.post("/login")
def login(password: str = Form(...)):
    if not config.APP_PASSWORD or not hmac.compare_digest(password, config.APP_PASSWORD):
        return RedirectResponse("/login?erro=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, _session_value(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
                     secure=config.PUBLIC_BASE_URL.startswith("https://"))
    return resp


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


@app.post("/api/upload")
def api_upload(file: UploadFile = File(...), options: str = Form("{}")):
    """Recebe o vídeo do usuário (streaming para o disco) e inicia o processamento."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"Formato não suportado ({ext or 'sem extensão'}). Use MP4, MOV, WebM ou MKV.")
    try:
        opts = NewJob(url="upload", **json.loads(options or "{}")).model_dump(exclude={"url"})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"opções inválidas: {e}")
    job_id = jobs.new_id()
    dest = jobs.job_dir(job_id) / f"upload{ext}"
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    with open(dest, "wb") as out:
        while chunk := file.file.read(4 * 1024 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                shutil.rmtree(jobs.job_dir(job_id), ignore_errors=True)
                raise HTTPException(413, f"Arquivo maior que {config.MAX_UPLOAD_MB} MB")
            out.write(chunk)
    return jobs.create("", opts, job_id=job_id, upload_name=file.filename or "")


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


# ---------- OAuth (uma conta por rede: uso pessoal, dono "default") ----------
import json as _json
import secrets as _secrets

from .publishers import instagram

_STATE_FILE = config.TOKENS_DIR / "oauth_state.json"


def _new_state(platform: str, extra: dict | None = None) -> str:
    state = _secrets.token_urlsafe(24)
    _STATE_FILE.write_text(_json.dumps({"state": state, "platform": platform, **(extra or {})}))
    return state


def _check_state(platform: str, state: str) -> dict:
    saved = _json.loads(_STATE_FILE.read_text()) if _STATE_FILE.exists() else {}
    if not state or saved.get("state") != state or saved.get("platform") != platform:
        raise HTTPException(400, "state OAuth inválido; tente conectar de novo")
    _STATE_FILE.unlink(missing_ok=True)
    return saved


def _connected(platform: str, name: str):
    on_connect(platform, name)
    return HTMLResponse(f"<p style='font-family:sans-serif'>{platform} conectado: <b>{name}</b>. Pode fechar esta aba.</p>")


def on_connect(platform: str, name: str) -> None:
    """Gancho opcional chamado quando uma conta é conectada."""


@app.get("/auth/youtube")
def auth_youtube():
    state = _new_state("youtube")
    url, verifier = youtube.auth_url(state)
    _STATE_FILE.write_text(_json.dumps({"state": state, "platform": "youtube", "verifier": verifier}))
    return RedirectResponse(url)


@app.get("/auth/youtube/callback")
def auth_youtube_cb(request: Request, state: str = ""):
    saved = _check_state("youtube", state)
    return _connected("youtube", youtube.handle_callback(str(request.url), state, saved.get("verifier"), "default"))


@app.get("/auth/tiktok")
def auth_tiktok():
    return RedirectResponse(tiktok.auth_url(_new_state("tiktok")))


@app.get("/auth/tiktok/callback")
def auth_tiktok_cb(code: str = "", state: str = ""):
    _check_state("tiktok", state)
    return _connected("tiktok", tiktok.handle_callback(code, "default"))


@app.get("/auth/instagram")
def auth_instagram():
    return RedirectResponse(instagram.auth_url(_new_state("instagram")))


@app.get("/auth/instagram/callback")
def auth_instagram_cb(code: str = "", state: str = ""):
    _check_state("instagram", state)
    return _connected("instagram", instagram.handle_callback(code, "default"))


def main():
    import uvicorn

    host_port = config.PUBLIC_BASE_URL.rsplit(":", 1)
    port = int(host_port[1]) if len(host_port) == 2 and host_port[1].isdigit() else 8000
    uvicorn.run("clipforge.app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
