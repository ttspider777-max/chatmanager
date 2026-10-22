import time

import aiosqlite

from config import DB_PATH, ELITE

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, name TEXT,
  account INTEGER DEFAULT 0, bonds INTEGER DEFAULT 0,
  invested INTEGER DEFAULT 0, bonds_bought INTEGER DEFAULT 0,
  deposit INTEGER DEFAULT 0, deposit_ts REAL DEFAULT 0,
  bonus_ts REAL DEFAULT 0, msgs INTEGER DEFAULT 0, banned INTEGER DEFAULT 0,
  created REAL, seen REAL
);
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY, title TEXT, type TEXT, added_by INTEGER, active INTEGER DEFAULT 1,
  welcome TEXT, rules TEXT, antilink INTEGER DEFAULT 0, antiflood INTEGER DEFAULT 0, joined REAL
);
CREATE TABLE IF NOT EXISTS wallets(
  user_id INTEGER, chat_id INTEGER, balance INTEGER DEFAULT 0, PRIMARY KEY(user_id, chat_id)
);
CREATE TABLE IF NOT EXISTS warns(chat_id INTEGER, user_id INTEGER, n INTEGER DEFAULT 0, PRIMARY KEY(chat_id, user_id));
CREATE TABLE IF NOT EXISTS bans(chat_id INTEGER, user_id INTEGER, name TEXT, ts REAL, PRIMARY KEY(chat_id, user_id));
CREATE TABLE IF NOT EXISTS city(
  id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0, players_total INTEGER DEFAULT 0,
  bonds_sold INTEGER DEFAULT 0, announced INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS elite(key TEXT PRIMARY KEY, owner_id INTEGER, until REAL DEFAULT 0, earned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS props(user_id INTEGER, item TEXT, ts REAL, PRIMARY KEY(user_id, item));
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, amount INTEGER, bonds INTEGER DEFAULT 0, uses INTEGER);
CREATE TABLE IF NOT EXISTS promo_used(code TEXT, user_id INTEGER, PRIMARY KEY(code, user_id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, val TEXT);
"""


async def init():
    global _conn
    _conn = await aiosqlite.connect(DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.executescript(SCHEMA)
    await _conn.execute("INSERT OR IGNORE INTO city(id) VALUES(1)")
    for k in ELITE:
        await _conn.execute("INSERT OR IGNORE INTO elite(key) VALUES(?)", (k,))
    await _conn.commit()


async def close():
    if _conn:
        await _conn.close()


async def one(q, a=()):
    cur = await _conn.execute(q, a)
    r = await cur.fetchone()
    await cur.close()
    return r


async def many(q, a=()):
    cur = await _conn.execute(q, a)
    r = await cur.fetchall()
    await cur.close()
    return r


async def run(q, a=()) -> int:
    cur = await _conn.execute(q, a)
    await _conn.commit()
    n = cur.rowcount
    await cur.close()
    return n


async def scalar(q, a=(), default=0):
    r = await one(q, a)
    return r[0] if r and r[0] is not None else default


# ---------- пользователи / чаты ----------
async def touch_user(u):
    now = time.time()
    await run(
        "INSERT INTO users(id,username,name,created,seen) VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET username=excluded.username,name=excluded.name,seen=excluded.seen",
        (u.id, (u.username or "").lower() or None, u.full_name, now, now))


async def get_user(uid):
    return await one("SELECT * FROM users WHERE id=?", (uid,))


async def find_user(token: str):
    token = token.strip()
    if token.lstrip("-").isdigit():
        return await get_user(int(token))
    return await one("SELECT * FROM users WHERE username=?", (token.lstrip("@").lower(),))


async def upsert_chat(chat, added_by=None, active=1):
    await run(
        "INSERT INTO chats(id,title,type,added_by,active,joined) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title,type=excluded.type,active=excluded.active,"
        "added_by=COALESCE(?,chats.added_by)",
        (chat.id, chat.title, chat.type, added_by, active, time.time(), added_by))


async def get_chat(cid):
    return await one("SELECT * FROM chats WHERE id=?", (cid,))


async def get_setting(key, default=""):
    r = await one("SELECT val FROM settings WHERE key=?", (key,))
    return r[0] if r else default


async def set_setting(key, val):
    await run("INSERT INTO settings(key,val) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET val=excluded.val", (key, val))
