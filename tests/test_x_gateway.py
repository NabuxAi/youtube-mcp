import os,tempfile
os.environ.setdefault("APP_SECRET_KEY","test-secret-that-is-long-enough-for-fernet-123456")
os.environ.setdefault("PUBLIC_BASE_URL","http://localhost:8000")
os.environ.setdefault("X_CLIENT_ID","test-client")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN","internal-test-token")
from app.db import Database
from app.x_api import pkce_pair

def test_pkce_pair_is_valid_shape():
    verifier,challenge=pkce_pair();assert len(verifier)>40;assert len(challenge)>=43;assert verifier!=challenge

def test_x_tokens_encrypted_and_owner_scoped():
    with tempfile.TemporaryDirectory() as tmp:
        db=Database(f"{tmp}/x.db");a=db.create_owner();b=db.create_owner()
        x=db.upsert_account(owner_id=a,x_user_id="42",username="alice",name="Alice",access_token="access-secret",refresh_token="refresh-secret",expires_at=9999999999,scopes=["tweet.read"])
        assert x["account_key"].startswith("x_");assert x["access_enc"]!="access-secret";assert db.account_tokens(x["id"])==("access-secret","refresh-secret")
        try:
            db.upsert_account(owner_id=b,x_user_id="42",username="other",name="Other",access_token="x",refresh_token="y",expires_at=None,scopes=[]);assert False
        except ValueError:pass
        assert db.accounts_for_owner(b)==[];db.close()

def test_cache_search():
    with tempfile.TemporaryDirectory() as tmp:
        db=Database(f"{tmp}/x.db");o=db.create_owner();a=db.upsert_account(owner_id=o,x_user_id="1",username="u",name="U",access_token="a",refresh_token="r",expires_at=9999999999,scopes=[])
        db.cache_items(o,a["id"],"post",[{"id":"p1","text":"AI launch in Oman","created_at":"2026-09-09T00:00:00Z"},{"id":"p2","text":"other"}])
        r=db.search_cache(a["id"],"Oman");assert len(r)==1;assert r[0]["remote_id"]=="p1";db.close()
