#!/usr/bin/env python3
"""Nabux YouTube MCP Gateway."""
from __future__ import annotations
import logging,re,sys
from app import config
class PathTokenMiddleware:
 _re=re.compile(r"^/t/([A-Za-z0-9_\-]{16,})(/mcp/?)$")
 def __init__(self,app):self.app=app
 async def __call__(self,scope,receive,send):
  if scope["type"]=="http":
   m=self._re.match(scope.get("path",""))
   if m:
    h=[(k,v) for k,v in scope.get("headers",[]) if k.lower()!=b"authorization"];h.append((b"authorization",f"Bearer {m.group(1)}".encode()));scope=dict(scope);scope["headers"]=h;scope["path"]=config.MCP_PATH;scope["raw_path"]=config.MCP_PATH.encode()
  await self.app(scope,receive,send)
def build_app():
 from mcp.server.auth.settings import AuthSettings,ClientRegistrationOptions,RevocationOptions
 from mcp.server.fastmcp import FastMCP
 from pydantic import AnyHttpUrl
 from app import tools,web,internal_api
 from app.db import get_db
 from app.oauth import SCOPE,get_provider
 config.DATA_DIR.mkdir(parents=True,exist_ok=True);config.DB_PATH.parent.mkdir(parents=True,exist_ok=True)
 db=get_db();p=get_provider();m=FastMCP(config.APP_NAME,host=config.MCP_HOST,port=config.MCP_PORT,streamable_http_path=config.MCP_PATH,stateless_http=True,json_response=True,auth=AuthSettings(issuer_url=AnyHttpUrl(config.PUBLIC_BASE_URL),resource_server_url=AnyHttpUrl(config.PUBLIC_BASE_URL+config.MCP_PATH),client_registration_options=ClientRegistrationOptions(enabled=True,valid_scopes=[SCOPE],default_scopes=[SCOPE]),revocation_options=RevocationOptions(enabled=True)),auth_server_provider=p);tools.register(m,db);web.register(m,p,db);internal_api.register(m,db);return PathTokenMiddleware(m.streamable_http_app())
def main():
 logging.basicConfig(level=logging.INFO);config.validate();import uvicorn;print(f"{config.APP_NAME}: {config.PUBLIC_BASE_URL}{config.MCP_PATH} (Official Google YouTube APIs; Nabux MCP gateway)",file=sys.stderr);uvicorn.run(build_app(),host=config.MCP_HOST,port=config.MCP_PORT,proxy_headers=True,forwarded_allow_ips="*",log_level="info")
if __name__=="__main__":main()