import sqlite3
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "warehouse.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT,
            note TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_lines (
            line_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            qty_required REAL NOT NULL,
            qty_allocated REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
        """)

        conn.commit()


def _physical_stock_by_item():
    totals = defaultdict(float)
    for row in get_current_stock():
        d = dict(row)
        totals[d["item_code"]] += float(d["stock_qty"])
    return dict(totals)


def get_physical_stock_by_item():
    """ロケーション横断の現物在庫合計（商品コードごと）。"""
    return _physical_stock_by_item()


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


def create_order_with_lines(reference, note, line_items):
    """
    line_items: (item_code, qty_required) のリスト（画面上の順で引当プールを消費）。
    戻り値: (order_id, results)。有効行がなければ (None, [])。
    results は各明細の dict（qty_pending = 未引当）。
    """
    prepared = []
    for raw_item, qty_required in line_items:
        item_code = (raw_item or "").strip()
        if not item_code:
            continue
        req = float(qty_required)
        if req <= 0:
            continue
        prepared.append((item_code, req))

    if not prepared:
        return None, []

    physical = _physical_stock_by_item()

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT item_code, COALESCE(SUM(qty_allocated), 0)
        FROM order_lines
        GROUP BY item_code
        """)
        allocated_prior = {r[0]: float(r[1]) for r in cur.fetchall()}

        pool = defaultdict(float)
        for k, v in physical.items():
            pool[k] += v
        for k, v in allocated_prior.items():
            pool[k] -= v

        cur.execute(
            "INSERT INTO orders (reference, note) VALUES (?, ?)",
            (reference or None, note or None),
        )
        order_id = cur.lastrowid
        results = []

        for item_code, req in prepared:
            avail = max(0.0, pool.get(item_code, 0.0))
            alloc = min(req, avail)
            pool[item_code] = pool.get(item_code, 0.0) - alloc

            cur.execute("""
            INSERT INTO order_lines (order_id, item_code, qty_required, qty_allocated)
            VALUES (?, ?, ?, ?)
            """, (order_id, item_code, req, alloc))
            results.append({
                "item_code": item_code,
                "qty_required": req,
                "qty_allocated": alloc,
                "qty_pending": req - alloc,
            })

        conn.commit()
        return order_id, results


def get_recent_order_lines(limit=50):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            o.order_id,
            o.reference,
            o.created_at AS order_created,
            l.line_id,
            l.item_code,
            l.qty_required,
            l.qty_allocated,
            (l.qty_required - l.qty_allocated) AS qty_pending
        FROM order_lines l
        JOIN orders o ON o.order_id = l.order_id
        ORDER BY l.line_id DESC
        LIMIT ?
        """, (limit,))
        return cur.fetchall()