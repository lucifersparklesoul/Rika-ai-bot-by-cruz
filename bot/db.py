import sqlite3
import json
import os
from datetime import datetime
from typing import List, Tuple, Optional
import numpy as np

from .config import settings

os.makedirs(os.path.dirname(settings.DB_PATH) or '.', exist_ok=True)


def init_db():
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        content TEXT,
        embedding TEXT,
        created_at TEXT
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_at TEXT
    )
    ''')
    # bans table includes an is_global flag for "global bans"
    cur.execute('''
    CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        reason TEXT,
        created_at TEXT,
        is_global INTEGER DEFAULT 0
    )
    ''')
    conn.commit()

    # run lightweight migration: ensure the is_global column exists (for older DBs)
    try:
        cur.execute("PRAGMA table_info(bans)")
        cols = [r[1] for r in cur.fetchall()]
        if 'is_global' not in cols:
            cur.execute('ALTER TABLE bans ADD COLUMN is_global INTEGER DEFAULT 0')
            conn.commit()
    except Exception:
        pass

    return conn


conn = init_db()


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


# Messages / embeddings
def save_message(user_id: int, role: str, content: str, embedding: Optional[List[float]] = None):
    cur = conn.cursor()
    emb_json = None
    if embedding is not None:
        emb_json = json.dumps([float(x) for x in embedding])
    cur.execute('INSERT INTO messages (user_id, role, content, embedding, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, role, content, emb_json, _now_iso()))
    conn.commit()
    return cur.lastrowid


def get_recent_messages(user_id: int, limit: int = 20) -> List[Tuple[int, str, str]]:
    cur = conn.cursor()
    cur.execute('SELECT id, role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?', (user_id, limit))
    rows = cur.fetchall()
    return [(r[0], r[1], r[2]) for r in rows][::-1]


def _load_embeddings_for_user(user_id: int):
    cur = conn.cursor()
    cur.execute('SELECT id, content, embedding FROM messages WHERE user_id = ? AND embedding IS NOT NULL', (user_id,))
    rows = cur.fetchall()
    ids = []
    contents = []
    embs = []
    for r in rows:
        ids.append(r[0])
        contents.append(r[1])
        embs.append(np.array(json.loads(r[2]), dtype=float))
    if embs:
        matrix = np.vstack(embs)
    else:
        matrix = np.empty((0,))
    return ids, contents, matrix


def get_relevant_memories(user_id: int, query_embedding: List[float], top_k: int = 5, min_score: float = 0.65):
    ids, contents, matrix = _load_embeddings_for_user(user_id)
    if matrix.size == 0:
        return []
    query = np.array(query_embedding, dtype=float)
    # cosine similarity
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) + 1e-12)
    dots = matrix.dot(query)
    scores = dots / (norms + 1e-12)
    ranked_idx = np.argsort(-scores)
    results = []
    for idx in ranked_idx[:top_k]:
        score = float(scores[idx])
        if score >= min_score:
            results.append({
                'id': ids[idx],
                'content': contents[idx],
                'score': score
            })
    return results


def clear_memory(user_id: Optional[int] = None):
    cur = conn.cursor()
    if user_id is None:
        cur.execute('DELETE FROM messages')
    else:
        cur.execute('DELETE FROM messages WHERE user_id = ?', (user_id,))
    conn.commit()


# Settings helpers
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    cur = conn.cursor()
    cur.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cur.fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str):
    cur = conn.cursor()
    cur.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()


# Admin management
def add_admin(user_id: int) -> bool:
    cur = conn.cursor()
    try:
        cur.execute('INSERT OR REPLACE INTO admins (user_id, added_at) VALUES (?, ?)', (user_id, _now_iso()))
        conn.commit()
        return True
    except Exception:
        return False


def remove_admin(user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
    changed = cur.rowcount
    conn.commit()
    return changed > 0


def list_admins() -> List[int]:
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM admins')
    rows = cur.fetchall()
    return [r[0] for r in rows]


def is_admin(user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM admins WHERE user_id = ? LIMIT 1', (user_id,))
    return cur.fetchone() is not None


# Ban management
def add_ban(user_id: int, reason: Optional[str] = None, is_global: bool = False) -> bool:
    cur = conn.cursor()
    try:
        cur.execute('INSERT OR REPLACE INTO bans (user_id, reason, created_at, is_global) VALUES (?, ?, ?, ?)', (user_id, reason or '', _now_iso(), 1 if is_global else 0))
        conn.commit()
        return True
    except Exception:
        return False


def remove_ban(user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
    changed = cur.rowcount
    conn.commit()
    return changed > 0


def is_banned(user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute('SELECT reason, created_at, is_global FROM bans WHERE user_id = ? LIMIT 1', (user_id,))
    row = cur.fetchone()
    return row is not None


def is_globally_banned(user_id: int) -> bool:
    cur = conn.cursor()
    cur.execute('SELECT is_global FROM bans WHERE user_id = ? LIMIT 1', (user_id,))
    row = cur.fetchone()
    return (row is not None) and (int(row[0]) == 1)


def add_global_ban(user_id: int, reason: Optional[str] = None) -> bool:
    # global ban: mark ban as global and remove admin if present
    ok = add_ban(user_id, reason, is_global=True)
    try:
        remove_admin(user_id)
    except Exception:
        pass
    return ok


def remove_global_ban(user_id: int) -> bool:
    # remove ban row entirely (global or not)
    return remove_ban(user_id)


def list_bans() -> List[Tuple[int, str, str, int]]:
    cur = conn.cursor()
    cur.execute('SELECT user_id, reason, created_at, is_global FROM bans')
    rows = cur.fetchall()
    return [(r[0], r[1], r[2], int(r[3] if r[3] is not None else 0)) for r in rows]
