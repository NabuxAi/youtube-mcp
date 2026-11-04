"""OAuth 2.1 authorization server for YouTube MCP clients."""
from __future__ import annotations
import time
from typing import Optional
from mcp.server.auth.provider import AccessToken,AuthorizationCode,AuthorizationParams,AuthorizeError,OAuthAuthorizationServerProvider,RefreshToken,TokenError,construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull,OAuthToken
from pydantic import AnyUrl
from . import config,security
from .db import Database,get_db
SCOPE="youtube";PERSONAL_CLIENT_ID="personal"
class OwnerAccessToken(AccessToken):owner_id:int=0
class OwnerRefreshToken(RefreshToken):owner_id:int=0;pair_id:str=""
class OwnerAuthCode(AuthorizationCode):owner_id:int=0
class Transaction:
 __slots__=("id","client_id","params","created")
 def __init__(self,id,client,params):self.id=id;self.client_id=client.client_id or "";self.params=params;self.created=time.time()
class YouTubeOAuthProvider(OAuthAuthorizationServerProvider[OwnerAuthCode,OwnerRefreshToken,OwnerAccessToken]):
 def __init__(self,db:Optional[Database]=None):self._db=db;self.transactions={}
 @property
 def db(self):return self._db or get_db()
 async def get_client(self,i):
  d=self.db.get_client(i);return OAuthClientInformationFull.model_validate(d) if d else None
 async def register_client(self,c):
  if not c.client_id:c.client_id=security.new_token(16)
  self.db.save_client(c.client_id,c.model_dump(mode="json",exclude_none=True))
 def _sweep(self):
  cut=time.time()-config.AUTH_CODE_TTL
  for k,t in list(self.transactions.items()):
   if t.created<cut:self.transactions.pop(k,None)
 async def authorize(self,client,params):
  self._sweep()
  if params.scopes and any(s!=SCOPE for s in params.scopes):raise AuthorizeError("invalid_scope",f"Only '{SCOPE}' is supported")
  t=Transaction(security.new_token(24),client,params);self.transactions[t.id]=t;return f"{config.PUBLIC_BASE_URL}/connect?txn={t.id}"
 def get_transaction(self,i):self._sweep();return self.transactions.get(i or "")
 def complete_transaction(self,i,o):
  t=self.transactions.pop(i,None)
  if not t:raise ValueError("Authorization request expired")
  p=t.params;code=security.new_token(32);self.db.save_auth_code(code,t.client_id,o,{"scopes":[SCOPE],"code_challenge":p.code_challenge,"redirect_uri":str(p.redirect_uri),"redirect_uri_provided_explicitly":p.redirect_uri_provided_explicitly,"resource":p.resource},time.time()+config.AUTH_CODE_TTL);return construct_redirect_uri(str(p.redirect_uri),code=code,state=p.state)
 async def load_authorization_code(self,client,code):
  d=self.db.peek_auth_code(code)
  if not d or d["client_id"]!=client.client_id:return None
  return OwnerAuthCode(code=d["code"],scopes=d["scopes"],expires_at=d["expires_at"],client_id=d["client_id"],code_challenge=d["code_challenge"],redirect_uri=AnyUrl(d["redirect_uri"]),redirect_uri_provided_explicitly=d["redirect_uri_provided_explicitly"],resource=d.get("resource"),owner_id=d["owner_id"])
 async def exchange_authorization_code(self,client,code):
  d=self.db.pop_auth_code(code.code)
  if not d or d["expires_at"]<time.time():raise TokenError("invalid_grant","authorization code expired")
  return self._issue(client.client_id or "",d["owner_id"],d["scopes"])
 def _issue(self,cid,oid,scopes,label=None):
  pair=security.new_token(12);a=security.new_token(32);r=security.new_token(32);now=int(time.time());self.db.save_token(a,kind="access",client_id=cid,owner_id=oid,scopes=scopes,pair_id=pair,expires_at=now+config.ACCESS_TOKEN_TTL,label=label);self.db.save_token(r,kind="refresh",client_id=cid,owner_id=oid,scopes=scopes,pair_id=pair,expires_at=now+config.REFRESH_TOKEN_TTL,label=label);return OAuthToken(access_token=a,token_type="Bearer",expires_in=config.ACCESS_TOKEN_TTL,scope=" ".join(scopes),refresh_token=r)
 def issue_personal_token(self,oid,label="dashboard"):
  t=security.new_token(32);self.db.save_token(t,kind="access",client_id=PERSONAL_CLIENT_ID,owner_id=oid,scopes=[SCOPE],pair_id=security.new_token(12),expires_at=None,label=label);return t
 async def load_refresh_token(self,client,tok):
  d=self.db.get_token(tok,kind="refresh")
  if not d or d["client_id"]!=client.client_id:return None
  return OwnerRefreshToken(token=tok,client_id=d["client_id"],scopes=d["scopes"],expires_at=d["expires_at"],owner_id=d["owner_id"],pair_id=d["pair_id"])
 async def exchange_refresh_token(self,client,tok,scopes):
  if not self.db.get_owner(tok.owner_id):raise TokenError("invalid_grant","owner disconnected")
  self.db.revoke_pair(tok.pair_id);return self._issue(client.client_id or "",tok.owner_id,scopes or [SCOPE])
 async def load_access_token(self,tok):
  d=self.db.get_token(tok,kind="access")
  if not d:return None
  return OwnerAccessToken(token=tok,client_id=d["client_id"],scopes=d["scopes"],expires_at=d["expires_at"],owner_id=d["owner_id"])
 async def revoke_token(self,tok):
  d=self.db.get_token(tok.token)
  if d:self.db.revoke_pair(d["pair_id"])
_provider:Optional[YouTubeOAuthProvider]=None
def get_provider():
 global _provider
 if _provider is None:_provider=YouTubeOAuthProvider()
 return _provider
