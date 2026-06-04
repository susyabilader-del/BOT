import aiosqlite
import os
from datetime import datetime
from config import Config


async def get_db():
    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(Config.DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            group_type TEXT NOT NULL,  -- 'source' veya 'verify'
            message_id INTEGER NOT NULL,
            user_id INTEGER,
            username TEXT,
            text TEXT,
            date TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_id, message_id)
        );

        CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_msg_id INTEGER,
            verify_msg_id INTEGER,
            source_text TEXT,
            verify_text TEXT,
            match_score REAL,
            status TEXT DEFAULT 'pending',  -- 'confirmed', 'denied', 'pending', 'partial'
            rule_name TEXT,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            rule_type TEXT NOT NULL,  -- 'keyword', 'pattern', 'user_claim', 'amount', 'custom'
            source_pattern TEXT,
            verify_pattern TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scan_state (
            group_id TEXT PRIMARY KEY,
            last_message_id INTEGER DEFAULT 0,
            last_scan_time TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_messages_group ON messages(group_id, group_type);
        CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
        CREATE INDEX IF NOT EXISTS idx_verifications_status ON verifications(status);
    """)
    await db.commit()
    await db.close()


async def save_message(group_id, group_type, message_id, user_id, username, text, date):
    db = await get_db()
    try:
        await db.execute("""
            INSERT OR IGNORE INTO messages (group_id, group_type, message_id, user_id, username, text, date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (str(group_id), group_type, message_id, user_id, username, text, date))
        await db.commit()
    finally:
        await db.close()


async def save_verification(source_msg_id, verify_msg_id, source_text, verify_text, match_score, status, rule_name, details=""):
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO verifications (source_msg_id, verify_msg_id, source_text, verify_text, match_score, status, rule_name, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_msg_id, verify_msg_id, source_text, verify_text, match_score, status, rule_name, details))
        await db.commit()
    finally:
        await db.close()


async def get_unverified_messages(group_type="source", limit=100):
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT * FROM messages 
            WHERE group_type = ? 
            AND message_id NOT IN (SELECT source_msg_id FROM verifications WHERE source_msg_id IS NOT NULL)
            ORDER BY date DESC LIMIT ?
        """, (group_type, limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_messages_by_group(group_type, since_date=None, limit=500):
    db = await get_db()
    try:
        if since_date:
            cursor = await db.execute("""
                SELECT * FROM messages WHERE group_type = ? AND date >= ? ORDER BY date DESC LIMIT ?
            """, (group_type, since_date, limit))
        else:
            cursor = await db.execute("""
                SELECT * FROM messages WHERE group_type = ? ORDER BY date DESC LIMIT ?
            """, (group_type, limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_scan_state(group_id):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM scan_state WHERE group_id = ?", (str(group_id),))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_scan_state(group_id, last_message_id):
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO scan_state (group_id, last_message_id, last_scan_time)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET last_message_id = ?, last_scan_time = ?
        """, (str(group_id), last_message_id, datetime.now().isoformat(),
              last_message_id, datetime.now().isoformat()))
        await db.commit()
    finally:
        await db.close()


async def get_rules(active_only=True):
    db = await get_db()
    try:
        if active_only:
            cursor = await db.execute("SELECT * FROM rules WHERE is_active = 1")
        else:
            cursor = await db.execute("SELECT * FROM rules")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def add_rule(name, rule_type, source_pattern, verify_pattern=None):
    db = await get_db()
    try:
        await db.execute("""
            INSERT OR REPLACE INTO rules (name, rule_type, source_pattern, verify_pattern)
            VALUES (?, ?, ?, ?)
        """, (name, rule_type, source_pattern, verify_pattern))
        await db.commit()
    finally:
        await db.close()


async def get_verification_stats():
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT status, COUNT(*) as count FROM verifications GROUP BY status
        """)
        rows = await cursor.fetchall()
        return {row["status"]: row["count"] for row in rows}
    finally:
        await db.close()


async def get_recent_verifications(limit=10):
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT * FROM verifications ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()
