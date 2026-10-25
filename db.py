"""SQLite 存储层：站点库的唯一事实来源。"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "sites.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    category TEXT DEFAULT '',
    discovered_from TEXT DEFAULT '',
    discovered_at REAL NOT NULL,
    last_scan_at REAL DEFAULT 0,
    scan_status TEXT DEFAULT 'pending',   -- pending / ok / unreachable / blocked
    payment_channels TEXT DEFAULT '[]',   -- JSON array，强信号，e.g. ["stripe","creem"]
    weak_channels TEXT DEFAULT '[]',      -- JSON array，弱信号（仅页面提及）
    has_pricing INTEGER DEFAULT 0,
    min_price_usd REAL DEFAULT 0,
    visits_monthly INTEGER DEFAULT 0,     -- 手动录入或对接流量 API 后回填
    revenue_signal REAL DEFAULT 0,        -- 估算月收款信号（美元）
    status TEXT DEFAULT 'active'          -- active / removed(站长要求下榜)
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
    if "weak_channels" not in cols:  # 旧库迁移
        conn.execute("ALTER TABLE sites ADD COLUMN weak_channels TEXT DEFAULT '[]'")
        conn.commit()
    return conn


def upsert_site(conn: sqlite3.Connection, domain: str, discovered_from: str = "",
                name: str = "", description: str = "") -> bool:
    """新增站点；已存在则返回 False。domain 统一小写、去 www。"""
    domain = domain.lower().strip().removeprefix("www.")
    if not domain or "." not in domain:
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO sites (domain, name, description, discovered_from, discovered_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (domain, name, description, discovered_from, time.time()),
    )
    conn.commit()
    return cur.rowcount > 0


def pending_sites(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sites WHERE scan_status = 'pending' AND status = 'active'"
        " ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def save_scan(conn: sqlite3.Connection, domain: str, result: dict) -> None:
    conn.execute(
        "UPDATE sites SET last_scan_at = ?, scan_status = ?, payment_channels = ?,"
        " weak_channels = ?, has_pricing = ?, min_price_usd = ? WHERE domain = ?",
        (time.time(), result["status"], json.dumps(result["channels"], ensure_ascii=False),
         json.dumps(result.get("weak_channels", []), ensure_ascii=False),
         int(result["has_pricing"]), result["min_price_usd"], domain),
    )
    conn.commit()


def set_visits(conn: sqlite3.Connection, domain: str, visits: int) -> None:
    conn.execute("UPDATE sites SET visits_monthly = ? WHERE domain = ?", (visits, domain))
    conn.commit()


def all_scanned(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sites WHERE scan_status = 'ok' AND status = 'active'"
        " ORDER BY revenue_signal DESC, id"
    ).fetchall()
