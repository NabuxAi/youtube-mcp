"""SQLite persistence for multi-user YouTube MCP."""
from __future__ import annotations
import json,sqlite3,threading,time
from contextlib import contextmanager
from typing import Optional
from . import config,security
_SCHEMA="""
CREATE TABLE IF NOT EXISTS owners(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at INTEGER NOT NULL,last_seen_at INTEGER);
CREATE TABLE IF NOT EXISTS youtube_accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL,account_key TEXT UNIQUE NOT NULL,channel_id TEXT UNIQUE NOT NULL,title TEXT,access_enc TEXT NOT NULL,refresh_enc TEXT,token_expires_at INTEGER,is_default INTEGER NOT NULL DEFAULT 0,connected INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,FOREIGN KEY(owner_id) REFERENCES owners(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS youtube_accounts_owner ON youtube_accounts(owner_id,id);
CREATE TABLE IF NOT EXISTS oauth_clients(client_id TEXT PRIMARY KEY,data_json TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS auth_codes(code TEXT PRIMARY KEY,client_id TEXT NOT NULL,owner_id INTEGER NOT NULL,data_json TEXT NOT NULL,expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(token_hash TEXT PRIMARY KEY,kind TEXT NOT NULL,client_id TEXT NOT NULL,owner_id INTEGER NOT NULL,scopes TEXT NOT NULL,pair_id TEXT NOT NULL,label TEXT,expires_at INTEGER,revoked INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_states(state TEXT PRIMARY KEY,owner_id INTEGER,mcp_txn TEXT,return_to TEXT,code_verifier TEXT,expires_at INTEGER NOT NULL);
"""
class Database:
 def __init__(self,path:Optional[str]=None):
  self.path=str(path or config.DB_PATH); self._lock=threading.RLock(); self._conn=sqlite3.connect(self.path,check_same_thread=False,isolation_level=None); self._conn.row_factory=sqlite3.Row; self._conn.execute("PRAGMA journal_mode=WAL"); self._conn.execute("PRAGMA foreign_keys=ON"); self._conn.executescript(_SCHEMA)
 @contextmanager
 def _tx(self):
  with self._lock:
   self._conn.execute("BEGIN")
   try:yield self._conn;self._conn.execute("COMMIT")
   except Exception:self._conn.execute("ROLLBACK");raise
 def _one(self,q,a=()):
  with self._lock:return self._conn.execute(q,a).fetchone()
 def _all(self,q,a=()):
  with self._lock:return self._conn.execute(q,a).fetchall()
 def close(self):self._conn.close()
 def create_owner(self):
  n=int(time.time())
  with self._tx() as c:return int(c.execute("INSERT INTO owners(created_at,last_seen_at) VALUES(?,?)",(n,n)).lastrowid)
 def get_owner(self,i):
  r=self._one("SELECT * FROM owners WHERE id=?",(i,));return dict(r) if r else None
 def touch_owner(self,i):
  with self._tx() as c:c.execute("UPDATE owners SET last_seen_at=? WHERE id=?",(int(time.time()),i))
 def account_by_channel_id(self,i):
  r=self._one("SELECT * FROM youtube_accounts WHERE channel_id=?",(str(i),));return dict(r) if r else None
 def account_by_key(self,k):
  r=self._one("SELECT * FROM youtube_accounts WHERE account_key=?",(k,));return dict(r) if r else None
 def account_by_id(self,i):
  r=self._one("SELECT * FROM youtube_accounts WHERE id=?",(i,));return dict(r) if r else None
 def accounts_for_owner(self,o):return [dict(r) for r in self._all("SELECT * FROM youtube_accounts WHERE owner_id=? ORDER BY is_default DESC,id",(o,))]
 def default_account(self,o):
  r=self._one("SELECT * FROM youtube_accounts WHERE owner_id=? AND connected=1 ORDER BY is_default DESC,id LIMIT 1",(o,));return dict(r) if r else None
 def upsert_account(self,*,owner_id,channel_id,title,access_token,refresh_token,expires_at):
  now=int(time.time());ae=security.encrypt(access_token);re=security.encrypt(refresh_token) if refresh_token else None
  with self._tx() as c:
   r=c.execute("SELECT * FROM youtube_accounts WHERE channel_id=?",(str(channel_id),)).fetchone()
   if r:
    if int(r["owner_id"])!=int(owner_id):raise ValueError("This YouTube channel is already connected to another user")
    if not re:re=r["refresh_enc"]
    c.execute("UPDATE youtube_accounts SET title=?,access_enc=?,refresh_enc=?,token_expires_at=?,connected=1,updated_at=? WHERE id=?",(title,ae,re,expires_at,now,r["id"]));aid=int(r["id"])
   else:
    count=c.execute("SELECT COUNT(*) FROM youtube_accounts WHERE owner_id=?",(owner_id,)).fetchone()[0];key="yt_"+security.new_token(18)
    aid=int(c.execute("INSERT INTO youtube_accounts(owner_id,account_key,channel_id,title,access_enc,refresh_enc,token_expires_at,is_default,connected,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)",(owner_id,key,str(channel_id),title,ae,re,expires_at,1 if count==0 else 0,now,now)).lastrowid)
  return self.account_by_id(aid) or {}
 def credentials(self,aid):
  a=self.account_by_id(aid)
  if not a or not a.get("connected"):raise KeyError("YouTube channel not connected")
  return security.decrypt(a["access_enc"]),security.decrypt(a["refresh_enc"]) if a.get("refresh_enc") else None
 def update_access(self,aid,token,expires_at,refresh_token=None):
  with self._tx() as c:
   if refresh_token:c.execute("UPDATE youtube_accounts SET access_enc=?,refresh_enc=?,token_expires_at=?,updated_at=? WHERE id=?",(security.encrypt(token),security.encrypt(refresh_token),expires_at,int(time.time()),aid))
   else:c.execute("UPDATE youtube_accounts SET access_enc=?,token_expires_at=?,updated_at=? WHERE id=?",(security.encrypt(token),expires_at,int(time.time()),aid))
 def set_default_account(self,o,aid):
  with self._tx() as c:
   if not c.execute("SELECT id FROM youtube_accounts WHERE id=? AND owner_id=? AND connected=1",(aid,o)).fetchone():return False
   c.execute("UPDATE youtube_accounts SET is_default=0 WHERE owner_id=?",(o,));c.execute("UPDATE youtube_accounts SET is_default=1 WHERE id=?",(aid,));return True
 def save_oauth_state(self,state,*,owner_id,mcp_txn,return_to,code_verifier):
  with self._tx() as c:c.execute("INSERT INTO oauth_states(state,owner_id,mcp_txn,return_to,code_verifier,expires_at) VALUES(?,?,?,?,?,?)",(state,owner_id,mcp_txn,return_to,code_verifier,int(time.time())+config.META_STATE_TTL))
 def pop_oauth_state(self,state):
  with self._tx() as c:
   r=c.execute("SELECT * FROM oauth_states WHERE state=?",(state,)).fetchone()
   if not r:return None
   c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
  d=dict(r);return None if d["expires_at"]<time.time() else d
 def save_client(self,i,d):
  with self._tx() as c:c.execute("INSERT OR REPLACE INTO oauth_clients(client_id,data_json,created_at) VALUES(?,?,?)",(i,json.dumps(d),int(time.time())))
 def get_client(self,i):
  r=self._one("SELECT data_json FROM oauth_clients WHERE client_id=?",(i,));return json.loads(r["data_json"]) if r else None
 def save_auth_code(self,code,client_id,owner_id,data,expires_at):
  with self._tx() as c:c.execute("INSERT INTO auth_codes(code,client_id,owner_id,data_json,expires_at) VALUES(?,?,?,?,?)",(code,client_id,owner_id,json.dumps(data),expires_at))
 def peek_auth_code(self,code):
  r=self._one("SELECT * FROM auth_codes WHERE code=?",(code,));
  if not r:return None
  d=json.loads(r["data_json"]);d.update({"code":r["code"],"client_id":r["client_id"],"owner_id":r["owner_id"],"expires_at":r["expires_at"]});return d
 def pop_auth_code(self,code):
  with self._tx() as c:
   r=c.execute("SELECT * FROM auth_codes WHERE code=?",(code,)).fetchone()
   if not r:return None
   c.execute("DELETE FROM auth_codes WHERE code=?",(code,))
  d=json.loads(r["data_json"]);d.update({"code":r["code"],"client_id":r["client_id"],"owner_id":r["owner_id"],"expires_at":r["expires_at"]});return d
 def save_token(self,token,*,kind,client_id,owner_id,scopes,pair_id,expires_at,label=None):
  with self._tx() as c:c.execute("INSERT INTO tokens(token_hash,kind,client_id,owner_id,scopes,pair_id,label,expires_at,revoked,created_at) VALUES(?,?,?,?,?,?,?,?,0,?)",(security.hash_token(token),kind,client_id,owner_id," ".join(scopes),pair_id,label,expires_at,int(time.time())))
 def get_token(self,token,kind=None):
  r=self._one("SELECT * FROM tokens WHERE token_hash=?",(security.hash_token(token),));
  if not r:return None
  d=dict(r)
  if kind and d["kind"]!=kind:return None
  if d["revoked"] or (d["expires_at"] and d["expires_at"]<time.time()):return None
  d["scopes"]=d["scopes"].split() if d["scopes"] else [];return d
 def revoke_pair(self,p):
  with self._tx() as c:c.execute("UPDATE tokens SET revoked=1 WHERE pair_id=?",(p,))
 def purge_expired(self):
  with self._tx() as c:c.execute("DELETE FROM oauth_states WHERE expires_at<?",(int(time.time()),));c.execute("DELETE FROM auth_codes WHERE expires_at<?",(time.time(),));c.execute("DELETE FROM tokens WHERE revoked=1 OR (expires_at IS NOT NULL AND expires_at<?)",(int(time.time())-604800,))
_db:Optional[Database]=None
def get_db():
 global _db
 if _db is None:_db=Database()
 return _db
def set_db(db):
 global _db;_db=db
