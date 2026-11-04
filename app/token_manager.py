"""Google OAuth token lifecycle for YouTube accounts."""
from __future__ import annotations
import time
from .db import Database,get_db
from .youtube import YouTubeClient,refresh_access,YouTubeError
async def client_for_account(database:Database,account:dict):
    access,refresh=database.credentials(int(account["id"]));exp=account.get("token_expires_at")
    if not exp or int(exp)-int(time.time())<300:
        if not refresh:raise YouTubeError("Google refresh token is unavailable; reconnect the channel")
        access,new_exp=await refresh_access(refresh);database.update_access(int(account["id"]),access,new_exp)
    return YouTubeClient(access)
