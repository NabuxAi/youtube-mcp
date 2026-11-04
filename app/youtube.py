"""Official Google YouTube Data/Analytics API client and resumable uploader."""
from __future__ import annotations
import asyncio,base64,hashlib,json,mimetypes,os,tempfile,time
from urllib.parse import urlencode,urlparse
import httpx
from . import config
class YouTubeError(RuntimeError):pass

def pkce_pair():
    verifier=base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode(); challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(); return verifier,challenge
def authorization_url(state,challenge):
    q={"client_id":config.GOOGLE_CLIENT_ID,"redirect_uri":config.GOOGLE_REDIRECT_URI,"response_type":"code","scope":" ".join(config.GOOGLE_SCOPES),"access_type":"offline","include_granted_scopes":"true","prompt":"consent","state":state,"code_challenge":challenge,"code_challenge_method":"S256"};return config.GOOGLE_AUTH_URL+"?"+urlencode(q)
async def exchange_code(code,verifier):
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as c:r=await c.post(config.GOOGLE_TOKEN_URL,data={"client_id":config.GOOGLE_CLIENT_ID,"client_secret":config.GOOGLE_CLIENT_SECRET,"code":code,"code_verifier":verifier,"grant_type":"authorization_code","redirect_uri":config.GOOGLE_REDIRECT_URI})
    if r.status_code>=400:raise YouTubeError(f"Google token exchange failed: {r.text[:700]}")
    d=r.json();return d["access_token"],d.get("refresh_token"),int(time.time())+int(d.get("expires_in",3600))
async def refresh_access(refresh_token):
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as c:r=await c.post(config.GOOGLE_TOKEN_URL,data={"client_id":config.GOOGLE_CLIENT_ID,"client_secret":config.GOOGLE_CLIENT_SECRET,"refresh_token":refresh_token,"grant_type":"refresh_token"})
    if r.status_code>=400:raise YouTubeError(f"Google token refresh failed: {r.text[:700]}")
    d=r.json();return d["access_token"],int(time.time())+int(d.get("expires_in",3600))

def _public_https(url):
    u=urlparse(url or "")
    if u.scheme!="https" or not u.netloc:raise YouTubeError("media_url must be public HTTPS")
    return url
class YouTubeClient:
    def __init__(self,token):self.token=token
    async def _req(self,method,path,*,params=None,json_body=None,base=None):
        headers={"Authorization":f"Bearer {self.token}"};url=f"{base or config.YOUTUBE_API_BASE}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as c:r=await c.request(method,url,params=params,json=json_body,headers=headers)
        if r.status_code>=400:raise YouTubeError(f"YouTube API {r.status_code}: {r.text[:900]}")
        return r.json() if r.content else {"success":True}
    async def channels(self):return (await self._req("GET","channels",params={"part":"snippet,contentDetails,statistics","mine":"true","maxResults":50})).get("items",[])
    async def channel(self):
        rows=await self.channels()
        if not rows:raise YouTubeError("No YouTube channel is available for this Google authorization")
        return rows[0]
    async def list_videos(self,limit=25):
        ch=await self.channel();uploads=ch.get("contentDetails",{}).get("relatedPlaylists",{}).get("uploads")
        if not uploads:return []
        items=(await self._req("GET","playlistItems",params={"part":"snippet,contentDetails,status","playlistId":uploads,"maxResults":max(1,min(limit,50))})).get("items",[])
        ids=[x.get("contentDetails",{}).get("videoId") for x in items if x.get("contentDetails",{}).get("videoId")]
        if not ids:return items
        return (await self._req("GET","videos",params={"part":"snippet,contentDetails,status,statistics","id":",".join(ids),"maxResults":50})).get("items",[])
    async def video(self,video_id):
        items=(await self._req("GET","videos",params={"part":"snippet,contentDetails,status,statistics,processingDetails","id":video_id})).get("items",[]);return items[0] if items else None
    async def update_video(self,video_id,title,description="",tags=None,category_id="22",privacy_status=None):
        body={"id":video_id,"snippet":{"title":title,"description":description,"tags":tags or [],"categoryId":category_id}}
        parts="snippet"
        if privacy_status:body["status"]={"privacyStatus":privacy_status};parts+=" ,status"
        return await self._req("PUT","videos",params={"part":parts.replace(" ","")},json_body=body)
    async def comment_threads(self,video_id,limit=50):
        return (await self._req("GET","commentThreads",params={"part":"snippet,replies","videoId":video_id,"maxResults":max(1,min(limit,100)),"textFormat":"plainText"})).get("items",[])
    async def reply_comment(self,parent_id,text):return await self._req("POST","comments",params={"part":"snippet"},json_body={"snippet":{"parentId":parent_id,"textOriginal":text}})
    async def set_comment_moderation(self,comment_id,status="heldForReview",ban_author=False):
        return await self._req("POST","comments/setModerationStatus",params={"id":comment_id,"moderationStatus":status,"banAuthor":str(bool(ban_author)).lower()})
    async def playlists(self,limit=50):return (await self._req("GET","playlists",params={"part":"snippet,contentDetails,status","mine":"true","maxResults":max(1,min(limit,50))})).get("items",[])
    async def create_playlist(self,title,description="",privacy="private"):
        return await self._req("POST","playlists",params={"part":"snippet,status"},json_body={"snippet":{"title":title,"description":description},"status":{"privacyStatus":privacy}})
    async def add_to_playlist(self,playlist_id,video_id):
        return await self._req("POST","playlistItems",params={"part":"snippet"},json_body={"snippet":{"playlistId":playlist_id,"resourceId":{"kind":"youtube#video","videoId":video_id}}})
    async def analytics(self,start_date,end_date,metrics="views,estimatedMinutesWatched,averageViewDuration,likes,comments,subscribersGained",dimensions=None,filters=None,sort=None,max_results=50):
        p={"ids":"channel==MINE","startDate":start_date,"endDate":end_date,"metrics":metrics,"maxResults":max_results}
        if dimensions:p["dimensions"]=dimensions
        if filters:p["filters"]=filters
        if sort:p["sort"]=sort
        return await self._req("GET","reports",params=p,base=config.YOUTUBE_ANALYTICS_BASE)
    async def _download(self,url):
        _public_https(url); fd,path=tempfile.mkstemp(prefix="yt-upload-");os.close(fd);size=0;ctype="application/octet-stream";limit=config.MAX_REMOTE_UPLOAD_MB*1024*1024
        try:
            async with httpx.AsyncClient(timeout=None,follow_redirects=True) as c:
                async with c.stream("GET",url) as r:
                    if r.status_code>=400:raise YouTubeError(f"Failed to fetch media URL: HTTP {r.status_code}")
                    ctype=(r.headers.get("content-type") or ctype).split(";",1)[0]
                    with open(path,"wb") as f:
                        async for chunk in r.aiter_bytes(1024*1024):
                            size+=len(chunk)
                            if size>limit:raise YouTubeError(f"Remote upload exceeds MAX_REMOTE_UPLOAD_MB={config.MAX_REMOTE_UPLOAD_MB}")
                            f.write(chunk)
            return path,size,ctype
        except Exception:
            if os.path.exists(path):os.unlink(path)
            raise
    def _upload_sync(self,path,size,ctype,metadata):
        headers={"Authorization":f"Bearer {self.token}","Content-Type":"application/json; charset=UTF-8","X-Upload-Content-Length":str(size),"X-Upload-Content-Type":ctype}
        with httpx.Client(timeout=120) as c:
            r=c.post(f"{config.YOUTUBE_UPLOAD_BASE}/videos",params={"uploadType":"resumable","part":"snippet,status"},headers=headers,json=metadata)
            if r.status_code>=400:raise YouTubeError(f"Could not create YouTube upload session: {r.text[:700]}")
            session=r.headers.get("location")
            if not session:raise YouTubeError("YouTube did not return a resumable upload URL")
            chunk_size=8*1024*1024;start=0
            with open(path,"rb") as f:
                while start<size:
                    data=f.read(min(chunk_size,size-start));end=start+len(data)-1
                    rr=c.put(session,headers={"Content-Type":ctype,"Content-Length":str(len(data)),"Content-Range":f"bytes {start}-{end}/{size}"},content=data)
                    if rr.status_code in (200,201):return rr.json()
                    if rr.status_code!=308:raise YouTubeError(f"YouTube upload failed: {rr.status_code} {rr.text[:700]}")
                    start=end+1
        raise YouTubeError("Upload ended without a final YouTube response")
    async def upload_from_url(self,media_url,title,description="",tags=None,category_id="22",privacy_status="private",made_for_kids=False,contains_synthetic_media=False):
        path,size,ctype=await self._download(media_url)
        try:
            metadata={"snippet":{"title":title,"description":description,"tags":tags or [],"categoryId":category_id},"status":{"privacyStatus":privacy_status,"selfDeclaredMadeForKids":bool(made_for_kids),"containsSyntheticMedia":bool(contains_synthetic_media)}}
            return await asyncio.to_thread(self._upload_sync,path,size,ctype,metadata)
        finally:
            if os.path.exists(path):os.unlink(path)
