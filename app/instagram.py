"""Official Meta Instagram Graph API integration.

The MCP layer is built by Nabux; Instagram operations themselves use Meta's
supported Instagram Business Login + graph.instagram.com APIs. No private API,
password login, cookie scraping, Selenium, or sessionid automation is used.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from . import config


class InstagramError(RuntimeError):
    pass


def authorization_url(state: str) -> str:
    params = {
        "client_id": config.IG_APP_ID,
        "redirect_uri": config.IG_REDIRECT_URI,
        "response_type": "code",
        "scope": ",".join(config.IG_SCOPES),
        "enable_fb_login": "0",
        "force_authentication": "1",
        "state": state,
    }
    return f"{config.IG_AUTH_URL}?{urlencode(params)}"


async def _json_request(method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, follow_redirects=False) as client:
            response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise InstagramError(f"Meta network error: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text[:800]}
    if response.status_code >= 400 or (isinstance(body, dict) and body.get("error")):
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            msg = err.get("message") or str(err)
        else:
            msg = body.get("error_message") or body.get("message") or f"HTTP {response.status_code}"
        raise InstagramError(str(msg))
    return body if isinstance(body, dict) else {"data": body}


async def exchange_code(code: str) -> tuple[str, int | None]:
    """Exchange Instagram OAuth code and upgrade it to a long-lived token."""
    short = await _json_request(
        "POST",
        config.IG_TOKEN_URL,
        data={
            "client_id": config.IG_APP_ID,
            "client_secret": config.IG_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": config.IG_REDIRECT_URI,
            "code": code,
        },
    )
    token = short.get("access_token")
    if not token:
        raise InstagramError("Meta did not return an Instagram access token")

    # Instagram Login path: exchange the short-lived token for the supported
    # long-lived token. If Meta declines the exchange, do not lose a successful
    # login; keep the short token and its expiry metadata when present.
    try:
        long_lived = await _json_request(
            "GET",
            f"{config.IG_GRAPH_BASE}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": config.IG_APP_SECRET,
                "access_token": token,
            },
        )
        token = long_lived.get("access_token") or token
        expires_in = long_lived.get("expires_in")
    except InstagramError:
        expires_in = short.get("expires_in")

    expires_at = int(time.time()) + int(expires_in) if expires_in else None
    return str(token), expires_at


class InstagramClient:
    def __init__(self, access_token: str):
        if not access_token:
            raise InstagramError("Missing Instagram access token")
        self.access_token = access_token
        self.base = f"{config.IG_GRAPH_BASE}/{config.IG_GRAPH_VERSION}"

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        clean["access_token"] = self.access_token
        return await _json_request("GET", f"{self.base}/{path.lstrip('/')}", params=clean)

    async def post(self, path: str, **data: Any) -> dict[str, Any]:
        clean = {k: v for k, v in data.items() if v is not None}
        clean["access_token"] = self.access_token
        return await _json_request("POST", f"{self.base}/{path.lstrip('/')}", data=clean)

    async def delete(self, path: str, **params: Any) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None}
        clean["access_token"] = self.access_token
        return await _json_request("DELETE", f"{self.base}/{path.lstrip('/')}", params=clean)

    async def profile(self) -> dict[str, Any]:
        # Fields supported by professional accounts through Instagram Login.
        # Keep this conservative so login is not blocked by an optional field.
        data = await self.get("me", fields="id,user_id,username,account_type,media_count")
        ig_id = data.get("user_id") or data.get("id")
        if not ig_id:
            raise InstagramError("Could not resolve Instagram professional account id")
        data["resolved_id"] = str(ig_id)
        return data

    async def media(self, limit: int = 25) -> list[dict[str, Any]]:
        data = await self.get(
            "me/media",
            fields="id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,username",
            limit=max(1, min(int(limit), 100)),
        )
        return data.get("data") or []

    async def publishing_limit(self, ig_user_id: str) -> dict[str, Any]:
        return await self.get(f"{ig_user_id}/content_publishing_limit", fields="config,quota_usage")

    async def _publish_container(self, ig_user_id: str, creation_id: str) -> dict[str, Any]:
        if not creation_id:
            raise InstagramError("Meta did not return a media container id")
        result = await self.post(f"{ig_user_id}/media_publish", creation_id=creation_id)
        return {"ok": True, "media_id": result.get("id"), "creation_id": creation_id}

    async def _wait_ready(self, creation_id: str) -> None:
        for _ in range(config.PUBLISH_POLL_ATTEMPTS):
            state = await self.get(creation_id, fields="status_code,status")
            code = str(state.get("status_code") or "").upper()
            if code in {"FINISHED", "PUBLISHED"}:
                return
            if code in {"ERROR", "EXPIRED"}:
                raise InstagramError(state.get("status") or f"Instagram container {code.lower()}")
            await asyncio.sleep(config.PUBLISH_POLL_SECONDS)
        raise InstagramError("Instagram media processing timed out")

    async def publish_image(self, ig_user_id: str, image_url: str, caption: str = "") -> dict[str, Any]:
        if not image_url.startswith("https://"):
            raise InstagramError("image_url must be a public HTTPS URL")
        container = await self.post(f"{ig_user_id}/media", image_url=image_url, caption=caption[:2200])
        return await self._publish_container(ig_user_id, str(container.get("id") or ""))

    async def publish_carousel(self, ig_user_id: str, image_urls: list[str], caption: str = "") -> dict[str, Any]:
        if not 2 <= len(image_urls) <= 10:
            raise InstagramError("A carousel requires 2 to 10 images")
        child_ids = []
        for url in image_urls:
            if not url.startswith("https://"):
                raise InstagramError("Every carousel image must use a public HTTPS URL")
            child = await self.post(f"{ig_user_id}/media", image_url=url, is_carousel_item="true")
            child_ids.append(str(child.get("id") or ""))
        parent = await self.post(
            f"{ig_user_id}/media",
            media_type="CAROUSEL",
            children=",".join(child_ids),
            caption=caption[:2200],
        )
        result = await self._publish_container(ig_user_id, str(parent.get("id") or ""))
        result["child_count"] = len(child_ids)
        return result

    async def publish_reel(self, ig_user_id: str, video_url: str, caption: str = "",
                           share_to_feed: bool = True, cover_url: str | None = None) -> dict[str, Any]:
        if not video_url.startswith("https://"):
            raise InstagramError("video_url must be a public HTTPS URL")
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "share_to_feed": "true" if share_to_feed else "false",
        }
        if cover_url:
            if not cover_url.startswith("https://"):
                raise InstagramError("cover_url must be a public HTTPS URL")
            payload["cover_url"] = cover_url
        container = await self.post(f"{ig_user_id}/media", **payload)
        cid = str(container.get("id") or "")
        await self._wait_ready(cid)
        return await self._publish_container(ig_user_id, cid)

    async def publish_story(self, ig_user_id: str, *, image_url: str | None = None,
                            video_url: str | None = None) -> dict[str, Any]:
        if bool(image_url) == bool(video_url):
            raise InstagramError("Provide exactly one of image_url or video_url")
        if image_url:
            if not image_url.startswith("https://"):
                raise InstagramError("image_url must be a public HTTPS URL")
            container = await self.post(f"{ig_user_id}/media", media_type="STORIES", image_url=image_url)
            cid = str(container.get("id") or "")
        else:
            if not str(video_url).startswith("https://"):
                raise InstagramError("video_url must be a public HTTPS URL")
            container = await self.post(f"{ig_user_id}/media", media_type="STORIES", video_url=video_url)
            cid = str(container.get("id") or "")
            await self._wait_ready(cid)
        return await self._publish_container(ig_user_id, cid)

    async def comments(self, media_id: str, limit: int = 25) -> list[dict[str, Any]]:
        data = await self.get(
            f"{media_id}/comments",
            fields="id,text,username,timestamp,like_count,hidden,replies",
            limit=max(1, min(int(limit), 100)),
        )
        return data.get("data") or []

    async def reply_comment(self, comment_id: str, message: str) -> dict[str, Any]:
        return await self.post(f"{comment_id}/replies", message=message[:2200])

    async def hide_comment(self, comment_id: str, hide: bool = True) -> dict[str, Any]:
        return await self.post(comment_id, hide="true" if hide else "false")

    async def delete_comment(self, comment_id: str) -> dict[str, Any]:
        return await self.delete(comment_id)
