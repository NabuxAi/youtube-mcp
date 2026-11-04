"""MCP tools for connected YouTube channels."""
from __future__ import annotations
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from .db import Database,get_db
from .youtube import YouTubeError
from .token_manager import client_for_account
_db:Database|None=None
def db():return _db or get_db()
def _owner():
 t=get_access_token();o=int(getattr(t,"owner_id",0) or 0) if t else 0
 if not o:raise YouTubeError("Not authenticated. Connect YouTube first")
 return o
def _mine():return [a for a in db().accounts_for_owner(_owner()) if a.get("connected")]
def resolve(account=None):
 rows=_mine()
 if not rows:raise YouTubeError("No YouTube channel connected")
 if not account:return rows[0]
 k=str(account).strip().lstrip("@").lower()
 for i,a in enumerate(rows,1):
  if k in {str(i),str(a["id"]),str(a["channel_id"]),str(a.get("account_key") or "").lower(),str(a.get("title") or "").lower()}:return a
 raise YouTubeError(f"No connected channel matches {account!r}")
def safe(a):return {"account_key":a.get("account_key"),"channel_id":a.get("channel_id"),"title":a.get("title"),"default":bool(a.get("is_default")),"connected":bool(a.get("connected")),"token_expires_at":a.get("token_expires_at")}
async def client(a):return await client_for_account(db(),a)
def register(mcp:FastMCP,database:Database|None=None):
 global _db;_db=database or get_db()
 @mcp.tool()
 async def youtube_accounts()->dict:return {"ok":True,"accounts":[safe(a) for a in _mine()]}
 @mcp.tool()
 async def youtube_channel(account:str|None=None)->dict:
  a=resolve(account);return {"ok":True,"account":safe(a),"channel":await (await client(a)).channel()}
 @mcp.tool()
 async def youtube_list_videos(account:str|None=None,limit:int=25)->dict:
  a=resolve(account);rows=await (await client(a)).list_videos(limit);return {"ok":True,"account":safe(a),"count":len(rows),"videos":rows}
 @mcp.tool()
 async def youtube_get_video(video_id:str,account:str|None=None)->dict:
  a=resolve(account);return {"ok":True,"account":safe(a),"video":await (await client(a)).video(video_id)}
 @mcp.tool()
 async def youtube_upload_video(media_url:str,title:str,description:str="",tags:list[str]|None=None,category_id:str="22",privacy_status:str="private",made_for_kids:bool=False,contains_synthetic_media:bool=False,account:str|None=None)->dict:
  """Download a public HTTPS video to the gateway and upload it through YouTube's official resumable videos.insert flow."""
  a=resolve(account);r=await (await client(a)).upload_from_url(media_url,title,description,tags,category_id,privacy_status,made_for_kids,contains_synthetic_media);return {"ok":True,"account":safe(a),"video":r}
 @mcp.tool()
 async def youtube_update_video(video_id:str,title:str,description:str="",tags:list[str]|None=None,category_id:str="22",privacy_status:str|None=None,account:str|None=None)->dict:
  a=resolve(account);r=await (await client(a)).update_video(video_id,title,description,tags,category_id,privacy_status);return {"ok":True,"account":safe(a),"video":r}
 @mcp.tool()
 async def youtube_comments(video_id:str,account:str|None=None,limit:int=50)->dict:
  a=resolve(account);rows=await (await client(a)).comment_threads(video_id,limit);return {"ok":True,"account":safe(a),"count":len(rows),"comments":rows}
 @mcp.tool()
 async def youtube_reply_comment(parent_comment_id:str,text:str,account:str|None=None)->dict:
  a=resolve(account);r=await (await client(a)).reply_comment(parent_comment_id,text);return {"ok":True,"account":safe(a),"comment":r}
 @mcp.tool()
 async def youtube_moderate_comment(comment_id:str,status:str="heldForReview",ban_author:bool=False,account:str|None=None)->dict:
  a=resolve(account);r=await (await client(a)).set_comment_moderation(comment_id,status,ban_author);return {"ok":True,"account":safe(a),"result":r}
 @mcp.tool()
 async def youtube_playlists(account:str|None=None,limit:int=50)->dict:
  a=resolve(account);rows=await (await client(a)).playlists(limit);return {"ok":True,"account":safe(a),"count":len(rows),"playlists":rows}
 @mcp.tool()
 async def youtube_create_playlist(title:str,description:str="",privacy:str="private",account:str|None=None)->dict:
  a=resolve(account);r=await (await client(a)).create_playlist(title,description,privacy);return {"ok":True,"account":safe(a),"playlist":r}
 @mcp.tool()
 async def youtube_add_to_playlist(playlist_id:str,video_id:str,account:str|None=None)->dict:
  a=resolve(account);r=await (await client(a)).add_to_playlist(playlist_id,video_id);return {"ok":True,"account":safe(a),"item":r}
 @mcp.tool()
 async def youtube_analytics(start_date:str,end_date:str,metrics:str="views,estimatedMinutesWatched,averageViewDuration,likes,comments,subscribersGained",dimensions:str|None=None,filters:str|None=None,sort:str|None=None,max_results:int=50,account:str|None=None)->dict:
  a=resolve(account);r=await (await client(a)).analytics(start_date,end_date,metrics,dimensions,filters,sort,max_results);return {"ok":True,"account":safe(a),"report":r}
