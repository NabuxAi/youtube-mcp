"""Internal service contract used by Nabux Social Core."""
from __future__ import annotations
import hmac
from starlette.requests import Request
from starlette.responses import JSONResponse
from . import config
from .db import Database,get_db
from .youtube import YouTubeError
from .token_manager import client_for_account

def _ok(req:Request)->bool:return bool(config.INTERNAL_SERVICE_TOKEN) and hmac.compare_digest(req.headers.get("authorization",""),f"Bearer {config.INTERNAL_SERVICE_TOKEN}")
def register(mcp,database:Database|None=None):
    database=database or get_db()
    @mcp.custom_route("/internal/v1/accounts/{account_key}/publish",methods=["POST"])
    async def publish(req:Request):
        if not _ok(req):return JSONResponse({"detail":"unauthorized"},401)
        a=database.account_by_key(req.path_params["account_key"])
        if not a or not a.get("connected"):return JSONResponse({"detail":"account_not_found"},404)
        try:body=await req.json()
        except Exception:return JSONResponse({"detail":"invalid_json"},400)
        kind=str(body.get("kind") or "").lower()
        if kind!="video":return JSONResponse({"detail":"unsupported_publish_kind","supported":["video"]},400)
        url=body.get("media_url");title=str(body.get("title") or "").strip();description=str(body.get("text") or body.get("description") or "")
        if not url:return JSONResponse({"detail":"media_url_required"},400)
        if not title:return JSONResponse({"detail":"title_required"},400)
        try:
            client=await client_for_account(database,a)
            result=await client.upload_from_url(str(url),title,description,body.get("tags"),str(body.get("category_id") or "22"),str(body.get("privacy_status") or "private"),bool(body.get("made_for_kids",False)),bool(body.get("contains_synthetic_media",False)))
        except YouTubeError as exc:return JSONResponse({"detail":str(exc)},502)
        remote=result.get("id") if isinstance(result,dict) else None
        return JSONResponse({"ok":True,"provider":"youtube","kind":"video","remote_id":str(remote) if remote else None,"result":result})
