import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "warehouse.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            item_code TEXT PRIMARY KEY,
            item_name TEXT NOT NULL,
            unit TEXT DEFAULT 'pcs',
            is_active INTEGER DEFAULT 1
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            location_code TEXT PRIMARY KEY,
            zone TEXT,
            rack TEXT,
            level TEXT,
            slot TEXT,
            is_active INTEGER DEFAULT 1
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_type TEXT NOT NULL,
            item_code TEXT NOT NULL,
            location_code TEXT NOT NULL,
            qty REAL NOT NULL,
            lot_no TEXT,
            order_no TEXT,
            priority INTEGER,
            reason TEXT,
            operator TEXT,
            tx_time TEXT NOT NULL,
            related_tx_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()


def get_current_stock():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            item_code,
            location_code,
            SUM(
                CASE
                    WHEN tx_type IN ('receipt', 'move_in', 'count_plus') THEN qty
                    WHEN tx_type IN ('issue', 'move_out', 'count_minus') THEN -qty
                    ELSE 0
                END
            ) AS stock_qty
        FROM inventory_transactions
        GROUP BY item_code, location_code
        HAVING stock_qty <> 0
        ORDER BY item_code, location_code
        """)
        return cur.fetchall()


def insert_transaction(
    tx_type,
    item_code,
    location_code,
    qty,
    lot_no=None,
    order_no=None,
    priority=None,
    reason=None,
    operator=None,
    tx_time=None,
    related_tx_id=None,
):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO inventory_transactions (
            tx_type,
            item_code,
            location_code,
            qty,
            lot_no,
            order_no,
            priority,
            reason,
            operator,
            tx_time,
            related_tx_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx_type,
            item_code,
            location_code,
            qty,
            lot_no,
            order_no,
            priority,
            reason,
            operator,
            tx_time,
            related_tx_id,
        ))
        conn.commit()


def get_recent_transactions(limit=50):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            tx_id,
            tx_type,
            item_code,
            location_code,
            qty,
            lot_no,
            order_no,
            priority,
            reason,
            operator,
            tx_time,
            created_at
        FROM inventory_transactions
        ORDER BY tx_id DESC
        LIMIT ?
        """, (limit,))
        return cur.fetchall()