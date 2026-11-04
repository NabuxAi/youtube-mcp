"""Environment configuration for Nabux YouTube MCP Gateway."""
import os
from pathlib import Path

def _int(name,default):
    r=os.environ.get(name,"").strip(); return int(r) if r else default
APP_NAME=os.environ.get("APP_NAME","YouTube MCP by Nabux").strip() or "YouTube MCP by Nabux"
PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL","https://youtube.nabuxai.com").strip().rstrip("/")
APP_SECRET_KEY=os.environ.get("APP_SECRET_KEY","").strip()
DATA_DIR=Path(os.environ.get("DATA_DIR","/data")); DB_PATH=Path(os.environ.get("DB_PATH","") or (DATA_DIR/"youtube-mcp.db"))
MCP_HOST=os.environ.get("MCP_HOST","0.0.0.0"); MCP_PORT=_int("MCP_PORT",8000); MCP_PATH="/mcp"
GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID","").strip(); GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET","").strip()
GOOGLE_REDIRECT_URI=os.environ.get("GOOGLE_REDIRECT_URI","").strip() or f"{PUBLIC_BASE_URL}/youtube/callback"
GOOGLE_AUTH_URL="https://accounts.google.com/o/oauth2/v2/auth"; GOOGLE_TOKEN_URL="https://oauth2.googleapis.com/token"
GOOGLE_SCOPES=[s.strip() for s in os.environ.get("GOOGLE_SCOPES","https://www.googleapis.com/auth/youtube.readonly,https://www.googleapis.com/auth/youtube.upload,https://www.googleapis.com/auth/youtube.force-ssl,https://www.googleapis.com/auth/yt-analytics.readonly").split(",") if s.strip()]
YOUTUBE_API_BASE="https://www.googleapis.com/youtube/v3"; YOUTUBE_UPLOAD_BASE="https://www.googleapis.com/upload/youtube/v3"; YOUTUBE_ANALYTICS_BASE="https://youtubeanalytics.googleapis.com/v2"
INTERNAL_SERVICE_TOKEN=os.environ.get("INTERNAL_SERVICE_TOKEN","").strip()
ACCESS_TOKEN_TTL=_int("ACCESS_TOKEN_TTL",3600); REFRESH_TOKEN_TTL=_int("REFRESH_TOKEN_TTL",90*24*3600); AUTH_CODE_TTL=_int("AUTH_CODE_TTL",600); COOKIE_TTL=_int("COOKIE_TTL",30*24*3600); META_STATE_TTL=_int("META_STATE_TTL",900)
HTTP_TIMEOUT=float(os.environ.get("HTTP_TIMEOUT","60") or 60); MAX_REMOTE_UPLOAD_MB=_int("MAX_REMOTE_UPLOAD_MB",2048)
def validate():
    p=[]
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        import logging; logging.getLogger(__name__).warning("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required for OAuth logins.")
    if len(APP_SECRET_KEY)<32:p.append("APP_SECRET_KEY must be at least 32 characters")
    if not INTERNAL_SERVICE_TOKEN:p.append("INTERNAL_SERVICE_TOKEN is required")
    if not (PUBLIC_BASE_URL.startswith("https://") or PUBLIC_BASE_URL.startswith("http://localhost")):p.append("PUBLIC_BASE_URL must use HTTPS")
    if p:raise SystemExit("Configuration errors:\n- "+"\n- ".join(p))
    DATA_DIR.mkdir(parents=True,exist_ok=True); DB_PATH.parent.mkdir(parents=True,exist_ok=True)
