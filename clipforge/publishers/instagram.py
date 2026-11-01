"""Publicação de Reels via Instagram Graph API (upload resumable, sem URL pública).

Requisitos: conta Instagram Business/Creator ligada a uma Página do Facebook,
app na Meta com permissões `instagram_basic` e `instagram_content_publish`,
IG_USER_ID e um token de longa duração (IG_ACCESS_TOKEN).
"""
from __future__ import annotations

import os
import time
import urllib.parse

import requests

from .. import accounts, config

REDIRECT = f"{config.PUBLIC_BASE_URL}/auth/instagram/callback"
SCOPES = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement,business_management"


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{config.IG_GRAPH_VERSION}/{path}"


def _json(r: requests.Response) -> dict:
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API: {data.get('error', data)}")
    return data


def auth_url(state: str) -> str:
    if not (config.META_APP_ID and config.META_APP_SECRET):
        raise RuntimeError("Defina META_APP_ID e META_APP_SECRET no .env")
    q = {"client_id": config.META_APP_ID, "redirect_uri": REDIRECT, "state": state, "scope": SCOPES, "response_type": "code"}
    return f"https://www.facebook.com/{config.IG_GRAPH_VERSION}/dialog/oauth?" + urllib.parse.urlencode(q)


def handle_callback(code: str, owner: str) -> str:
    """Troca o code por um token de longa duração e encontra a conta do Instagram ligada à Página."""
    short = _json(requests.get(_graph("oauth/access_token"), params={
        "client_id": config.META_APP_ID, "client_secret": config.META_APP_SECRET,
        "redirect_uri": REDIRECT, "code": code}, timeout=30))["access_token"]
    long = _json(requests.get(_graph("oauth/access_token"), params={
        "grant_type": "fb_exchange_token", "client_id": config.META_APP_ID,
        "client_secret": config.META_APP_SECRET, "fb_exchange_token": short}, timeout=30))
    token = long["access_token"]
    pages = _json(requests.get(_graph("me/accounts"), params={
        "fields": "name,instagram_business_account{id,username}", "access_token": token}, timeout=30)).get("data", [])
    ig = next((p["instagram_business_account"] for p in pages if p.get("instagram_business_account")), None)
    if not ig:
        raise RuntimeError("Nenhuma conta Instagram Business/Creator ligada às suas Páginas do Facebook.")
    accounts.save("instagram", owner, {
        "ig_user_id": ig["id"], "username": ig.get("username", ""), "access_token": token,
        "expires_at": int(time.time()) + int(long.get("expires_in", 60 * 86400)),
    })
    return "@" + ig.get("username", "instagram")


def _creds(owner: str) -> tuple[str, str]:
    data = accounts.load("instagram", owner)
    if data:
        return data["ig_user_id"], data["access_token"]
    if owner == "default" and config.IG_USER_ID and config.IG_ACCESS_TOKEN:
        return config.IG_USER_ID, config.IG_ACCESS_TOKEN
    raise RuntimeError("Instagram não conectado.")


def is_connected(owner: str = "default") -> bool:
    try:
        _creds(owner)
        return True
    except RuntimeError:
        return False


def upload(video_path: str, caption: str, share_to_feed: bool = True, owner: str = "default") -> dict:
    ig_user_id, token = _creds(owner)

    container = _json(requests.post(
        _graph(f"{ig_user_id}/media"),
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption[:2200],
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": token,
        },
        timeout=60,
    ))
    cid = container["id"]
    upload_uri = container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{config.IG_GRAPH_VERSION}/{cid}"

    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        r = requests.post(
            upload_uri,
            data=fh,
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            timeout=600,
        )
    _json(r)

    status = ""
    for _ in range(90):
        st = _json(requests.get(_graph(cid), params={"fields": "status_code,status", "access_token": token}, timeout=30))
        status = st.get("status_code", "")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram não processou o vídeo: {st.get('status')}")
        time.sleep(5)
    if status != "FINISHED":
        raise RuntimeError("Tempo esgotado aguardando o Instagram processar o Reel")

    pub = _json(requests.post(_graph(f"{ig_user_id}/media_publish"), data={"creation_id": cid, "access_token": token}, timeout=60))
    media_id = pub["id"]
    link = _json(requests.get(_graph(media_id), params={"fields": "permalink", "access_token": token}, timeout=30)).get("permalink")
    return {"id": media_id, "url": link}
