import os,tempfile
os.environ.setdefault("APP_SECRET_KEY","test-secret-that-is-long-enough-for-fernet-123456")
os.environ.setdefault("PUBLIC_BASE_URL","http://localhost:8000")
os.environ.setdefault("GOOGLE_CLIENT_ID","test-client")
os.environ.setdefault("GOOGLE_CLIENT_SECRET","test-secret")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN","internal-test-token")
from app.db import Database

def test_google_tokens_are_encrypted_and_channel_is_owner_scoped():
 with tempfile.TemporaryDirectory() as t:
  db=Database(f"{t}/x.db");a=db.create_owner();b=db.create_owner();ch=db.upsert_account(owner_id=a,channel_id="UC123",title="Test",access_token="access-secret",refresh_token="refresh-secret",expires_at=9999999999)
  assert ch["account_key"].startswith("yt_") and ch["access_enc"]!="access-secret" and ch["refresh_enc"]!="refresh-secret"
  assert db.credentials(ch["id"])==("access-secret","refresh-secret")
  try:db.upsert_account(owner_id=b,channel_id="UC123",title="Other",access_token="x",refresh_token="y",expires_at=None)
  except ValueError:pass
  else:raise AssertionError("cross-owner channel move must fail")
  assert len(db.accounts_for_owner(a))==1 and not db.accounts_for_owner(b);db.close()

def test_refresh_token_is_preserved_when_google_does_not_return_a_new_one():
 with tempfile.TemporaryDirectory() as t:
  db=Database(f"{t}/x.db");o=db.create_owner();a=db.upsert_account(owner_id=o,channel_id="UC1",title="One",access_token="a1",refresh_token="r1",expires_at=1);db.upsert_account(owner_id=o,channel_id="UC1",title="One",access_token="a2",refresh_token=None,expires_at=2);assert db.credentials(a["id"])[1]=="r1";db.close()
