"""Official X API v2 client + OAuth 2.0 PKCE helpers."""
from __future__ import annotations
import base64,hashlib,json,time
from typing import Any
from urllib.parse import urlencode
import httpx
from . import config

class XError(RuntimeError): pass

def pkce_pair()->tuple[str,str]:
    import secrets
    verifier=secrets.token_urlsafe(48)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier,challenge

def authorization_url(state:str,challenge:str)->str:
    params={"response_type":"code","client_id":config.X_CLIENT_ID,"redirect_uri":config.X_REDIRECT_URI,"scope":" ".join(config.X_SCOPES),"state":state,"code_challenge":challenge,"code_challenge_method":"S256"}
    return f"{config.X_AUTH_URL}?{urlencode(params)}"

def _basic_auth()->tuple[str,str]|None:
    return (config.X_CLIENT_ID,config.X_CLIENT_SECRET) if config.X_CLIENT_SECRET else None

async def _json_request(method:str,url:str,**kwargs)->dict[str,Any]:
    try:
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as c:r=await c.request(method,url,**kwargs)
    except httpx.HTTPError as e:raise XError(f"X network error: {e}") from e
    try:body=r.json()
    except ValueError:body={"detail":r.text[:1200]}
    if r.status_code>=400:
        detail=body.get("detail") or body.get("title") or body.get("error_description") or body.get("error") or str(body)
        raise XError(f"X API {r.status_code}: {detail}")
    return body if isinstance(body,dict) else {"data":body}

async def exchange_code(code:str,verifier:str)->dict:
    data={"grant_type":"authorization_code","code":code,"redirect_uri":config.X_REDIRECT_URI,"code_verifier":verifier,"client_id":config.X_CLIENT_ID}
    kwargs={"data":data,"headers":{"Content-Type":"application/x-www-form-urlencoded"}}
    if _basic_auth():kwargs["auth"]=_basic_auth()
    return await _json_request("POST",config.X_TOKEN_URL,**kwargs)

async def refresh_token(refresh:str)->dict:
    data={"grant_type":"refresh_token","refresh_token":refresh,"client_id":config.X_CLIENT_ID}
    kwargs={"data":data,"headers":{"Content-Type":"application/x-www-form-urlencoded"}}
    if _basic_auth():kwargs["auth"]=_basic_auth()
    return await _json_request("POST",config.X_TOKEN_URL,**kwargs)

class XClient:
    def __init__(self,token:str):
        if not token:raise XError("Missing X access token")
        self.token=token
    async def request(self,method:str,path:str,*,params:dict|None=None,json_body:dict|None=None)->dict:
        url=f"{config.X_API_BASE}/{path.lstrip('/')}"
        return await _json_request(method.upper(),url,params=params,json=json_body,headers={"Authorization":f"Bearer {self.token}","Content-Type":"application/json"})
    async def me(self):return await self.request("GET","users/me",params={"user.fields":"id,name,username,description,profile_image_url,public_metrics,verified,created_at"})
    async def search_recent(self,query:str,max_results:int=25,next_token:str|None=None):
        p={"query":query,"max_results":max(10,min(max_results,100)),"tweet.fields":"id,text,author_id,created_at,conversation_id,lang,public_metrics,referenced_tweets","expansions":"author_id","user.fields":"id,name,username,profile_image_url"}
        if next_token:p["next_token"]=next_token
        return await self.request("GET","tweets/search/recent",params=p)
    async def user_posts(self,user_id:str,max_results:int=25,pagination_token:str|None=None):
        p={"max_results":max(5,min(max_results,100)),"tweet.fields":"id,text,created_at,conversation_id,public_metrics"}
        if pagination_token:p["pagination_token"]=pagination_token
        return await self.request("GET",f"users/{user_id}/tweets",params=p)
    async def mentions(self,user_id:str,max_results:int=25):
        return await self.request("GET",f"users/{user_id}/mentions",params={"max_results":max(5,min(max_results,100)),"tweet.fields":"id,text,author_id,created_at,conversation_id,public_metrics","expansions":"author_id","user.fields":"id,name,username"})
    async def create_post(self,text:str,reply_to:str|None=None,quote_id:str|None=None,media_ids:list[str]|None=None):
        body:dict[str,Any]={"text":text}
        if reply_to:body["reply"]={"in_reply_to_tweet_id":reply_to}
        if quote_id:body["quote_tweet_id"]=quote_id
        if media_ids:body["media"]={"media_ids":media_ids}
        return await self.request("POST","tweets",json_body=body)
    async def delete_post(self,post_id:str):return await self.request("DELETE",f"tweets/{post_id}")
    async def like(self,user_id:str,post_id:str):return await self.request("POST",f"users/{user_id}/likes",json_body={"tweet_id":post_id})
    async def unlike(self,user_id:str,post_id:str):return await self.request("DELETE",f"users/{user_id}/likes/{post_id}")
    async def follow(self,user_id:str,target_id:str):return await self.request("POST",f"users/{user_id}/following",json_body={"target_user_id":target_id})
    async def unfollow(self,user_id:str,target_id:str):return await self.request("DELETE",f"users/{user_id}/following/{target_id}")
    async def dm_events(self,max_results:int=100,pagination_token:str|None=None):
        p={"max_results":max(1,min(max_results,100)),"dm_event.fields":"id,event_type,text,sender_id,created_at,dm_conversation_id,attachments","expansions":"sender_id","user.fields":"id,name,username,profile_image_url"}
        if pagination_token:p["pagination_token"]=pagination_token
        return await self.request("GET","dm_events",params=p)
    async def dm_conversation(self,participant_id:str,max_results:int=100):
        return await self.request("GET",f"dm_conversations/with/{participant_id}/dm_events",params={"max_results":max(1,min(max_results,100)),"dm_event.fields":"id,event_type,text,sender_id,created_at,dm_conversation_id,attachments"})
    async def send_dm(self,participant_id:str,text:str,media_id:str|None=None):
        body:dict[str,Any]={"text":text}
        if media_id:body["attachments"]=[{"media_id":media_id}]
        return await self.request("POST",f"dm_conversations/with/{participant_id}/messages",json_body=body)
