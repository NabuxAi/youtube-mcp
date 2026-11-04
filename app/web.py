"""Google OAuth browser flow, YouTube dashboard, and trusted internal API."""
from __future__ import annotations
import html,hmac
from starlette.requests import Request
from starlette.responses import HTMLResponse,JSONResponse,RedirectResponse,Response
from . import config,security
from .db import Database,get_db
from .oauth import YouTubeOAuthProvider
from .youtube import YouTubeClient,YouTubeError,authorization_url,exchange_code,pkce_pair
from .token_manager import client_for_account
COOKIE="ytmcp_session"
def e(v):return html.escape(str(v if v is not None else ""),quote=True)
def page(t,b):return HTMLResponse(f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(t)} · {e(config.APP_NAME)}</title><style>body{{margin:0;background:#0f0f0f;color:#fff;font:15px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}main{{max-width:820px;margin:5vh auto;padding:16px}}.card{{background:#191919;border:1px solid #333;border-radius:18px;padding:28px}}p{{color:#aaa}}.btn,button{{display:inline-block;background:#ff0033;color:#fff;border:0;border-radius:10px;padding:11px 16px;text-decoration:none;font-weight:700;cursor:pointer}}code{{display:block;background:#090909;border:1px solid #333;border-radius:8px;padding:9px;word-break:break-all}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #333;text-align:left}}.ok{{border:1px solid #34d399;border-radius:9px;padding:10px}}.err{{border:1px solid #fb7185;border-radius:9px;padding:10px;color:#fb7185}}</style></head><body><main><div class='card'>{b}</div><p style='text-align:center'>Powered by Google YouTube Data & Analytics APIs · MCP gateway by Nabux</p></main></body></html>",headers={"Cache-Control":"no-store","X-Frame-Options":"DENY"})
def set_cookie(r:Response,o:int):r.set_cookie(COOKIE,security.sign_cookie(o),max_age=config.COOKIE_TTL,httponly=True,secure=config.PUBLIC_BASE_URL.startswith("https://"),samesite="lax",path="/")
def owner(req):return security.verify_cookie(req.cookies.get(COOKIE))
def csrf(req):return security.csrf_token(req.cookies.get(COOKIE,""))
def internal(req):return bool(config.INTERNAL_SERVICE_TOKEN) and hmac.compare_digest(req.headers.get("authorization",""),f"Bearer {config.INTERNAL_SERVICE_TOKEN}")
def public(a):return {"account_key":a.get("account_key"),"channel_id":a.get("channel_id"),"title":a.get("title"),"connected":bool(a.get("connected")),"default":bool(a.get("is_default")),"token_expires_at":a.get("token_expires_at")}
def register(mcp,provider:YouTubeOAuthProvider,database:Database|None=None):
 database=database or get_db()
 @mcp.custom_route("/",methods=["GET"])
 async def landing(req:Request):
  oid=owner(req);return page("YouTube MCP",f"<h1>YouTube MCP Gateway</h1><p>Channelها را با Google OAuth رسمی متصل کن؛ upload، comments، playlists و analytics از MCP در دسترس می‌شوند.</p><div class='ok'>No password/cookie/browser automation.</div><h2>MCP</h2><code>{e(config.PUBLIC_BASE_URL)}{e(config.MCP_PATH)}</code><p><a class='btn' href='/dashboard'>{'Dashboard' if oid else 'Connect YouTube'}</a></p>")
 @mcp.custom_route("/connect",methods=["GET"])
 async def connect(req:Request):
  txn=req.query_params.get("txn") or None;oid=owner(req)
  if txn and oid and provider.get_transaction(txn) and database.accounts_for_owner(oid):
   try:return RedirectResponse(provider.complete_transaction(txn,oid),302)
   except ValueError:pass
  state=security.new_token(24);ver,challenge=pkce_pair();database.save_oauth_state(state,owner_id=oid,mcp_txn=txn,return_to="/dashboard",code_verifier=ver);return RedirectResponse(authorization_url(state,challenge),302)
 @mcp.custom_route("/youtube/add",methods=["GET"])
 async def add(req:Request):
  oid=owner(req)
  if not oid:return RedirectResponse("/connect",302)
  state=security.new_token(24);ver,ch=pkce_pair();database.save_oauth_state(state,owner_id=oid,mcp_txn=None,return_to="/dashboard",code_verifier=ver);return RedirectResponse(authorization_url(state,ch),302)
 @mcp.custom_route("/youtube/callback",methods=["GET"])
 async def callback(req:Request):
  if req.query_params.get("error"):return page("OAuth error",f"<h1>Google authorization failed</h1><div class='err'>{e(req.query_params.get('error'))}</div>")
  st=database.pop_oauth_state(req.query_params.get("state") or "");code=req.query_params.get("code") or ""
  if not st or not code:return page("Expired","<h1>Invalid/expired authorization</h1>")
  try:
   access,refresh,exp=await exchange_code(code,st["code_verifier"]);channels=await YouTubeClient(access).channels()
   if not channels:raise YouTubeError("Google authorization returned no YouTube channels")
   existing=database.account_by_channel_id(channels[0]["id"]);oid=int(st.get("owner_id") or (existing["owner_id"] if existing else 0) or database.create_owner())
   for ch in channels:database.upsert_account(owner_id=oid,channel_id=ch["id"],title=ch.get("snippet",{}).get("title"),access_token=access,refresh_token=refresh,expires_at=exp)
   database.touch_owner(oid)
  except (YouTubeError,ValueError) as exc:return page("YouTube error",f"<h1>Connection failed</h1><div class='err'>{e(exc)}</div>")
  if st.get("mcp_txn"):
   try:target=provider.complete_transaction(st["mcp_txn"],oid);r=RedirectResponse(target,302);set_cookie(r,oid);return r
   except ValueError as exc:return page("Expired",f"<div class='err'>{e(exc)}</div>")
  r=RedirectResponse("/dashboard",303);set_cookie(r,oid);return r
 @mcp.custom_route("/dashboard",methods=["GET"])
 async def dashboard(req:Request):
  oid=owner(req)
  if not oid:return RedirectResponse("/connect",302)
  rows="".join(f"<tr><td>{e(a.get('title') or a['channel_id'])}</td><td><code>{e(a['account_key'])}</code></td><td>{'default' if a.get('is_default') else ''}</td></tr>" for a in database.accounts_for_owner(oid) if a.get("connected"));return page("Dashboard",f"<h1>YouTube MCP Dashboard</h1><p>Google access/refresh tokens encrypted at rest.</p><table><tr><th>Channel</th><th>Account Key</th><th></th></tr>{rows}</table><p><a class='btn' href='/youtube/add'>+ Connect another Google/YouTube account</a></p><h2>MCP</h2><code>{e(config.PUBLIC_BASE_URL)}{e(config.MCP_PATH)}</code><form method='post' action='/dashboard/token'><input type='hidden' name='csrf' value='{e(csrf(req))}'><button>Generate personal MCP token</button></form>")
 @mcp.custom_route("/dashboard/token",methods=["POST"])
 async def mcp_token(req:Request):
  oid=owner(req);form=await req.form()
  if not oid or not security.check_csrf(req.cookies.get(COOKIE),form.get("csrf")):return RedirectResponse("/connect",302)
  t=provider.issue_personal_token(oid);return page("Token",f"<h1>Personal MCP token</h1><code>{e(t)}</code><h2>Endpoint</h2><code>{e(config.PUBLIC_BASE_URL)}{e(config.MCP_PATH)}</code>")
 @mcp.custom_route("/internal/v1/accounts/{account_key}",methods=["GET"])
 async def ia(req:Request):
  if not internal(req):return JSONResponse({"detail":"unauthorized"},401)
  a=database.account_by_key(req.path_params["account_key"]);return JSONResponse({"ok":True,"account":public(a)}) if a and a.get("connected") else JSONResponse({"detail":"account_not_found"},404)
 @mcp.custom_route("/internal/v1/accounts/{account_key}/upload",methods=["POST"])
 async def upload(req:Request):
  if not internal(req):return JSONResponse({"detail":"unauthorized"},401)
  a=database.account_by_key(req.path_params["account_key"])
  if not a:return JSONResponse({"detail":"account_not_found"},404)
  try:
   d=await req.json();c=await client_for_account(database,a);r=await c.upload_from_url(str(d.get("media_url") or ""),str(d.get("title") or "Untitled"),str(d.get("description") or ""),d.get("tags"),str(d.get("category_id") or "22"),str(d.get("privacy_status") or "private"),bool(d.get("made_for_kids",False)),bool(d.get("contains_synthetic_media",False)));return JSONResponse({"ok":True,"video":r})
  except YouTubeError as exc:return JSONResponse({"detail":str(exc)},400)
