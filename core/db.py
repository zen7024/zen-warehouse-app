import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "warehouse.db"

# 引当明細が無い旧データ向けの出庫ロケーション（新規引当は allocation_details で実ロケーションへ記録）
SHIP_ISSUE_LOCATION = "__SHIP__"
DEFAULT_WAREHOUSE_CODE = "WH-001"

STATE_LABELS = {
    "UNALLOCATED": "未引当",
    "PARTIAL_ALLOCATED": "一部引当",
    "ALLOCATED": "引当済",
    "REALLOC_PENDING": "再引当待ち",
    "RELEASED": "解除済",
    "WORKING": "作業中",
    "PARTIAL_SHIPPED": "一部出荷",
    "SHIPPED": "出荷確定",
    "HOLD": "保留",
    "SENT_BACK": "差戻し",
    "CANCELLED": "キャンセル",
}

REASON_LABELS = {
    "NORMAL_SHIPMENT": "通常出荷",
    "SHORTAGE": "現物不足",
    "RELOCATION": "別ロケ再配分",
    "CUSTOMER_CHANGE": "客先変更",
    "PRIORITY_CHANGE": "優先変更",
    "PRIORITY_REALLOC": "優先案件へ再配分",
    "PRIORITY_OVERRIDE": "優先出荷割り込み",
    "WRONG_ALLOC": "誤引当",
    "STOCK_DIFF": "在庫差異",
    "UNPLANNED_LOCATION": "予定外ロケ",
    "DELAYED_RECEIPT": "入荷遅延",
    "FIFO_EXCEPTION": "FIFO例外",
    "COUNT_DIFF": "棚卸差異",
    "MANUAL_HOLD": "手動保留",
    "INTERRUPT": "割り込み中断",
    "OTHER": "その他",
}

APPROVAL_LABELS = {
    "NOT_REQUIRED": "承認不要",
    "WAITING": "承認待ち",
    "APPROVED": "承認済",
    "REJECTED": "却下",
}

STATE = {
    "LINE_OPEN": "未着手",
    "LINE_PARTIALLY_ALLOCATED": "一部引当",
    "LINE_ALLOCATED": "引当済",
    "LINE_PARTIALLY_SHIPPED": "一部出荷",
    "LINE_SHIPPED": "出荷完了",
    "LINE_HOLD": "保留",
    "LINE_CANCELLED": "キャンセル",
}


def update_line_state(qty_required, qty_allocated, shipped_qty, hold_flag):
    if hold_flag:
        return "LINE_HOLD"
    if shipped_qty >= qty_required - 1e-9:
        return "LINE_SHIPPED"
    if shipped_qty > 1e-9:
        return "LINE_PARTIALLY_SHIPPED"
    if qty_allocated >= qty_required - 1e-9:
        return "LINE_ALLOCATED"
    if qty_allocated > 1e-9:
        return "LINE_PARTIALLY_ALLOCATED"
    return "LINE_OPEN"


EVENT_LABELS = {
    "ALLOCATE": "引当実行",
    "SHIP_CONFIRM": "出荷確定",
    "RELEASE": "引当解除",
    "A06_HOLD": "A-06保留",
    "MOVE": "移動",
    "RECEIPT": "入庫",
    "ISSUE": "出庫",
    "COUNT_DIFF": "棚卸差異",
    "REALLOCATE": "再引当",
    "VIEW_ALLOCATABLE_STOCK": "引当可能在庫閲覧",
    "VIEW_CURRENT_STOCK": "現在庫閲覧",
    "STATE_CHANGE": "状態変更",
}


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
            shipped_qty REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS allocation_details (
            detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
            line_id INTEGER NOT NULL,
            location_code TEXT NOT NULL,
            allocated_qty REAL NOT NULL,
            shipped_qty REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (line_id) REFERENCES order_lines(line_id)
        )
        """)

        cur.execute("PRAGMA table_info(order_lines)")
        ol_cols = [r[1] for r in cur.fetchall()]
        if ol_cols and "shipped_qty" not in ol_cols:
            cur.execute(
                "ALTER TABLE order_lines ADD COLUMN shipped_qty REAL NOT NULL DEFAULT 0"
            )
        if ol_cols and "state_code" not in ol_cols:
            cur.execute(
                "ALTER TABLE order_lines ADD COLUMN state_code TEXT DEFAULT 'LINE_OPEN'"
            )
        if ol_cols and "state_reason" not in ol_cols:
            cur.execute("ALTER TABLE order_lines ADD COLUMN state_reason TEXT")
        if ol_cols and "hold_flag" not in ol_cols:
            cur.execute(
                "ALTER TABLE order_lines ADD COLUMN hold_flag INTEGER DEFAULT 0"
            )
        if ol_cols and "updated_at" not in ol_cols:
            cur.execute("ALTER TABLE order_lines ADD COLUMN updated_at TEXT")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_state_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            line_id INTEGER,
            state_code TEXT NOT NULL,
            state_reason TEXT,
            hold_flag INTEGER DEFAULT 0,
            hold_reason TEXT,
            approval_required INTEGER DEFAULT 0,
            approval_status TEXT DEFAULT 'NOT_REQUIRED',
            impact_order_count INTEGER DEFAULT 0,
            changed_by TEXT,
            changed_at TEXT NOT NULL,
            free_note TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (line_id) REFERENCES order_lines(line_id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            event_at TEXT NOT NULL,
            user_id TEXT,
            role_name TEXT,
            warehouse_code TEXT,
            order_id INTEGER,
            order_no TEXT,
            line_id INTEGER,
            item_code TEXT,
            location_code TEXT,
            before_value TEXT,
            after_value TEXT,
            reason_code TEXT,
            free_note TEXT
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


def get_allocation_strategy():
    # 現在は共通基盤の既定戦略として priority 固定（将来差し替え用の窓口）
    return "priority"


def get_allocated_qty_by_item():
    """order_lines の未出荷引当合計（qty_allocated - shipped_qty）を商品コード別に集計。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT item_code, COALESCE(SUM(qty_allocated - shipped_qty), 0) AS qty_allocated
        FROM order_lines
        GROUP BY item_code
        ORDER BY item_code
        """)
        return {row["item_code"]: float(row["qty_allocated"]) for row in cur.fetchall()}


def get_allocatable_stock_by_item():
    """
    商品別に物理在庫・引当済・引当可能在庫を返す（リストの dict）。

    - 引当可能在庫 = max(物理在庫 - 引当済, 0)
    - 物理在庫または引当に現れる商品コードをすべて含む（将来の優先度・バックオーダー拡張の土台）
    """
    physical = get_physical_stock_by_item()
    allocated = get_allocated_qty_by_item()
    codes = sorted(set(physical) | set(allocated))
    rows = []
    for item_code in codes:
        p = float(physical.get(item_code, 0.0))
        a = float(allocated.get(item_code, 0.0))
        rows.append({
            "item_code": item_code,
            "physical_qty": p,
            "allocated_qty": a,
            "allocatable_qty": max(p - a, 0.0),
        })
    return rows


def build_alloc_status(qty_required: float, qty_allocated: float) -> str:
    """
    明細の数量だけから見た引当充足度（未引当 / 一部引当 / 引当済）。
    order_state_logs の state_code とは別の表示用ラベル。
    """
    req = float(qty_required or 0)
    alloc = float(qty_allocated or 0)
    if alloc <= 1e-9:
        return "未引当"
    if alloc < req - 1e-9:
        return "一部引当"
    return "引当済"


def get_order_competition_by_item(item_code: str) -> list:
    """
    同一商品コードを持つ全出荷明細の横断一覧（案件競合の可視化用）。
    """
    code = (item_code or "").strip()
    if not code:
        return []
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                o.order_id,
                o.reference,
                l.line_id,
                l.item_code,
                l.qty_required,
                l.qty_allocated,
                l.shipped_qty,
                (l.qty_required - l.qty_allocated) AS qty_pending,
                (l.qty_allocated - l.shipped_qty) AS qty_unshipped,
                o.created_at
            FROM order_lines l
            INNER JOIN orders o ON o.order_id = l.order_id
            WHERE l.item_code = ?
            ORDER BY o.created_at ASC, o.order_id ASC, l.line_id ASC
            """,
            (code,),
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["alloc_status"] = build_alloc_status(d["qty_required"], d["qty_allocated"])
            rows.append(d)
        return rows


def _fetch_current_stock_rows(cur):
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


def _build_allocatable_pool(cur, item_code, strategy="priority"):
    """
    指定商品のロケーション別引当可能プールを優先順付きで返す。

    戻り値: [{"location_code": str, "qty": float, "priority": int|None}, ...]
    """
    cur.execute(
        """
        SELECT
            location_code,
            SUM(
                CASE
                    WHEN tx_type IN ('receipt', 'move_in', 'count_plus') THEN qty
                    WHEN tx_type IN ('issue', 'move_out', 'count_minus') THEN -qty
                    ELSE 0
                END
            ) AS stock_qty
        FROM inventory_transactions
        WHERE item_code = ?
        GROUP BY location_code
        HAVING stock_qty <> 0
        """,
        (item_code,),
    )
    stock_by_loc = {row["location_code"]: float(row["stock_qty"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT
            ad.location_code,
            COALESCE(SUM(ad.allocated_qty - ad.shipped_qty), 0) AS reserved
        FROM allocation_details ad
        JOIN order_lines ol ON ol.line_id = ad.line_id
        WHERE ol.item_code = ?
        GROUP BY ad.location_code
        """,
        (item_code,),
    )
    reserved_by_loc = {row["location_code"]: float(row["reserved"]) for row in cur.fetchall()}

    pool = []
    for loc, stock_qty in stock_by_loc.items():
        allocatable = max(stock_qty - reserved_by_loc.get(loc, 0.0), 0.0)
        if allocatable <= 0:
            continue
        pool.append({
            "location_code": loc,
            "qty": allocatable,
            "priority": None,
        })

    if not pool:
        return []

    if strategy == "priority":
        cur.execute(
            """
            SELECT location_code, MIN(priority) AS min_priority
            FROM inventory_transactions
            WHERE item_code = ? AND priority IS NOT NULL
            GROUP BY location_code
            """,
            (item_code,),
        )
        priority_by_loc = {
            row["location_code"]: int(row["min_priority"])
            for row in cur.fetchall()
            if row["min_priority"] is not None
        }
        for row in pool:
            row["priority"] = priority_by_loc.get(row["location_code"])
        pool.sort(key=lambda r: (r["priority"] is None, r["priority"] or 0, r["location_code"]))
        return pool

    if strategy == "location":
        pool.sort(key=lambda r: r["location_code"])
        return pool

    raise ValueError(f"Unknown allocation strategy: {strategy}")


def get_current_stock():
    with get_connection() as conn:
        cur = conn.cursor()
        return _fetch_current_stock_rows(cur)


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
    引当はロケーション別に allocation_details へ記録する（strategy に基づく優先順で消費）。

    戻り値: (order_id, results)。有効行がなければ (None, [])。
    results の各要素に qty_pending に加え allocations: [{location_code, qty}, ...] を含む。
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

    with get_connection() as conn:
        cur = conn.cursor()
        item_pools = {}
        strategy = get_allocation_strategy()

        cur.execute(
            "INSERT INTO orders (reference, note) VALUES (?, ?)",
            (reference or None, note or None),
        )
        order_id = cur.lastrowid
        results = []

        for item_code, req in prepared:
            if item_code not in item_pools:
                item_pools[item_code] = _build_allocatable_pool(
                    cur,
                    item_code,
                    strategy=strategy,
                )
            need = req
            details_to_insert = []
            for entry in item_pools[item_code]:
                if need <= 0:
                    break
                loc = entry["location_code"]
                avail = max(0.0, float(entry["qty"]))
                if avail <= 0:
                    continue
                take = min(need, avail)
                details_to_insert.append((loc, take))
                entry["qty"] = avail - take
                need -= take

            alloc = req - need
            line_state = update_line_state(req, alloc, 0, 0)
            line_updated_at = datetime.now().isoformat(timespec="seconds")

            cur.execute("""
            INSERT INTO order_lines
                (order_id, item_code, qty_required, qty_allocated, state_code, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (order_id, item_code, req, alloc, line_state, line_updated_at))
            line_id = cur.lastrowid

            for loc, take in details_to_insert:
                cur.execute("""
                INSERT INTO allocation_details (line_id, location_code, allocated_qty, shipped_qty)
                VALUES (?, ?, ?, 0)
                """, (line_id, loc, take))

            results.append({
                "item_code": item_code,
                "qty_required": req,
                "qty_allocated": alloc,
                "qty_pending": req - alloc,
                "allocations": [
                    {"location_code": loc, "qty": take}
                    for loc, take in details_to_insert
                ],
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
            l.shipped_qty,
            (l.qty_required - l.qty_allocated) AS qty_pending,
            (l.qty_allocated - l.shipped_qty) AS qty_unshipped
        FROM order_lines l
        JOIN orders o ON o.order_id = l.order_id
        ORDER BY l.line_id DESC
        LIMIT ?
        """, (limit,))
        return cur.fetchall()


def get_order_lines_pending_shipment():
    """
    qty_allocated > shipped_qty の order_lines をすべて返す（出荷確定候補の抽出用）。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            l.line_id,
            l.order_id,
            l.item_code,
            l.qty_required,
            l.qty_allocated,
            l.shipped_qty,
            (l.qty_allocated - l.shipped_qty) AS qty_unshipped
        FROM order_lines l
        WHERE l.qty_allocated > l.shipped_qty
        ORDER BY l.order_id, l.line_id
        """)
        return cur.fetchall()


def list_orders_for_ship_confirm():
    """出荷指示の一覧（新しい順）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT order_id, reference, created_at
        FROM orders
        ORDER BY order_id DESC
        """)
        return cur.fetchall()


def get_order_lines_shipment_view(order_id):
    """
    指定した出荷指示の明細（未出荷数量 = qty_allocated - shipped_qty を含む）。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            line_id,
            item_code,
            qty_required,
            qty_allocated,
            shipped_qty,
            (qty_allocated - shipped_qty) AS qty_unshipped
        FROM order_lines
        WHERE order_id = ?
        ORDER BY line_id
        """, (order_id,))
        return cur.fetchall()


def get_allocation_details_for_order(order_id):
    """指示に紐づくロケーション別引当明細（出荷進捗の内訳表示用）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            l.line_id,
            l.item_code,
            ad.location_code,
            ad.allocated_qty,
            ad.shipped_qty,
            (ad.allocated_qty - ad.shipped_qty) AS qty_unshipped
        FROM allocation_details ad
        JOIN order_lines l ON l.line_id = ad.line_id
        WHERE l.order_id = ?
        ORDER BY l.line_id, ad.detail_id
        """, (order_id,))
        return cur.fetchall()


def confirm_shipment_for_order(order_id, line_ship_qty_map=None, operator=None, reason=None):
    """
    指定数量（明細ごと）を inventory_transactions に issue として記録し、
    order_lines / allocation_details の shipped_qty を進める。

    allocation_details がある明細はロケーション別に issue。
    明細が無い旧データのみ SHIP_ISSUE_LOCATION へ集約 issue（後方互換）。

    line_ship_qty_map: {line_id: 今回出荷数量}
      - 未指定/None の場合は各明細の未出荷分を全量出荷（従来互換）
      - 指定時は 0 超かつ未出荷以下の数量のみ反映

    戻り値: (成功, メッセージ, 処理した行の要約リスト)
    """
    tx_time = datetime.now().isoformat(timespec="seconds")
    summary = []

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT reference FROM orders WHERE order_id = ?", (order_id,))
        orow = cur.fetchone()
        if not orow:
            return False, "出荷指示が見つかりません", []

        order_ref = orow["reference"]

        cur.execute("""
        SELECT line_id, item_code, qty_required, qty_allocated, shipped_qty,
               COALESCE(hold_flag, 0) AS hold_flag
        FROM order_lines
        WHERE order_id = ? AND qty_allocated > shipped_qty
        ORDER BY line_id
        """, (order_id,))
        pending = cur.fetchall()
        if not pending:
            return False, "未出荷の引当がありません（すべて出荷済みか、引当ゼロです）", []

        plan_map = {}
        if line_ship_qty_map:
            for k, v in line_ship_qty_map.items():
                try:
                    lid = int(k)
                    q = float(v)
                except (TypeError, ValueError):
                    return False, f"今回出荷数量の形式が不正です（line_id={k}）", []
                if q < 0:
                    return False, f"今回出荷数量は0以上で指定してください（line_id={lid}）", []
                plan_map[lid] = q

        base_reason = reason or "出荷確定"
        for line in pending:
            line_id = line["line_id"]
            item_code = line["item_code"]
            qty_req = float(line["qty_required"])
            qty_alloc = float(line["qty_allocated"])
            shipped_line = float(line["shipped_qty"])
            hold_flag = int(line["hold_flag"] or 0)
            to_ship_line = qty_alloc - shipped_line
            if to_ship_line <= 0:
                continue
            requested = to_ship_line
            if line_ship_qty_map is not None:
                requested = float(plan_map.get(line_id, 0.0))
                if requested <= 0:
                    continue
                if requested > to_ship_line + 1e-6:
                    return (
                        False,
                        f"明細 {line_id} の今回出荷数量が未出荷数量を超えています",
                        [],
                    )

            line_reason_base = f"{base_reason} (order_id={order_id}, line_id={line_id})"

            cur.execute("""
            SELECT detail_id, location_code, allocated_qty, shipped_qty
            FROM allocation_details
            WHERE line_id = ? AND allocated_qty > shipped_qty
            ORDER BY detail_id
            """, (line_id,))
            details = cur.fetchall()

            if details:
                remain_req = requested
                for det in details:
                    if remain_req <= 1e-9:
                        break
                    det_id = det["detail_id"]
                    loc = det["location_code"]
                    a = float(det["allocated_qty"])
                    s = float(det["shipped_qty"])
                    unshipped = a - s
                    if unshipped <= 0:
                        continue
                    to_ship = min(remain_req, unshipped)
                    if to_ship <= 0:
                        continue
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
                        "issue",
                        item_code,
                        loc,
                        to_ship,
                        None,
                        order_ref,
                        None,
                        f"{line_reason_base} detail_id={det_id} loc={loc}",
                        operator,
                        tx_time,
                        None,
                    ))
                    cur.execute(
                        "UPDATE allocation_details SET shipped_qty = ? WHERE detail_id = ?",
                        (s + to_ship, det_id),
                    )
                    remain_req -= to_ship
                    summary.append({
                        "line_id": line_id,
                        "item_code": item_code,
                        "location_code": loc,
                        "qty_shipped": to_ship,
                    })
                if remain_req > 1e-6:
                    conn.rollback()
                    return (
                        False,
                        f"明細 {line_id} のロケーション別未出荷が不足しているため出荷を中止しました",
                        [],
                    )

                new_shipped = shipped_line + requested
                new_state = update_line_state(qty_req, qty_alloc, new_shipped, hold_flag)
                cur.execute(
                    "UPDATE order_lines SET shipped_qty = ?, state_code = ?, updated_at = ? WHERE line_id = ?",
                    (new_shipped, new_state, datetime.now().isoformat(timespec="seconds"), line_id),
                )
            else:
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
                    "issue",
                    item_code,
                    SHIP_ISSUE_LOCATION,
                    requested,
                    None,
                    order_ref,
                    None,
                    line_reason_base,
                    operator,
                    tx_time,
                    None,
                ))
                new_shipped2 = shipped_line + requested
                new_state2 = update_line_state(qty_req, qty_alloc, new_shipped2, hold_flag)
                cur.execute(
                    "UPDATE order_lines SET shipped_qty = ?, state_code = ?, updated_at = ? WHERE line_id = ?",
                    (new_shipped2, new_state2, datetime.now().isoformat(timespec="seconds"), line_id),
                )
                summary.append({
                    "line_id": line_id,
                    "item_code": item_code,
                    "location_code": SHIP_ISSUE_LOCATION,
                    "qty_shipped": requested,
                })

        conn.commit()

    return True, f"出荷確定しました（{len(summary)} 件の出庫行）", summary


def list_orders_with_releasable_allocations():
    """未出荷の引当（qty_allocated > shipped_qty）を1行以上持つ出荷指示の一覧。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT DISTINCT o.order_id, o.reference, o.created_at
        FROM orders o
        INNER JOIN order_lines l ON l.order_id = o.order_id
        WHERE l.qty_allocated > l.shipped_qty
        ORDER BY o.order_id DESC
        """)
        return cur.fetchall()


def release_allocation_for_line(
    line_id,
    release_qty,
    reason_code=None,
    free_note=None,
    operator=None,
):
    """
    指定明細の未出荷引当のみを解除する。

    - allocation_details がある場合: detail_id 降順（後から積んだロットから）に未出荷分を減算。
      allocated_qty が 0 かつ出荷済 0 の行は削除。
    - 明細が無い旧データ: order_lines.qty_allocated のみ減算。

    戻り値: (成功, メッセージ)
    """
    try:
        rq = float(release_qty)
    except (TypeError, ValueError):
        return False, "解除数量が不正です"

    if rq <= 0:
        return False, "解除数量は0より大きくしてください"

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT
            l.order_id,
            o.reference,
            l.item_code,
            l.qty_required,
            l.qty_allocated,
            l.shipped_qty,
            COALESCE(l.hold_flag, 0) AS hold_flag
        FROM order_lines l
        JOIN orders o ON o.order_id = l.order_id
        WHERE l.line_id = ?
        """, (line_id,))
        line = cur.fetchone()
        if not line:
            return False, "明細が見つかりません"

        order_id = line["order_id"]
        order_ref = line["reference"]
        item_code = line["item_code"]
        qty_req = float(line["qty_required"])
        qty_alloc = float(line["qty_allocated"])
        shipped = float(line["shipped_qty"])
        hold_flag = int(line["hold_flag"] or 0)
        releasable = qty_alloc - shipped

        if rq > releasable + 1e-6:
            return False, f"解除可能数量は {releasable:g} までです"

        cur.execute(
            "SELECT COUNT(*) AS c FROM allocation_details WHERE line_id = ?",
            (line_id,),
        )
        has_details = cur.fetchone()["c"] > 0

        remaining = rq
        total_cut = 0.0

        if has_details:
            cur.execute("""
            SELECT detail_id, allocated_qty, shipped_qty
            FROM allocation_details
            WHERE line_id = ?
            ORDER BY detail_id DESC
            """, (line_id,))
            details = cur.fetchall()

            for det in details:
                if remaining <= 1e-9:
                    break
                d_id = det["detail_id"]
                a = float(det["allocated_qty"])
                s = float(det["shipped_qty"])
                u = a - s
                if u <= 1e-9:
                    continue
                t = min(remaining, u)
                new_a = a - t
                remaining -= t
                total_cut += t

                if new_a <= 1e-9:
                    cur.execute(
                        "DELETE FROM allocation_details WHERE detail_id = ?",
                        (d_id,),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE allocation_details
                        SET allocated_qty = ?
                        WHERE detail_id = ?
                        """,
                        (new_a, d_id),
                    )

            if remaining > 1e-6:
                conn.rollback()
                return (
                    False,
                    "allocation_details と order_lines の数量が一致しません。解除を中止しました。",
                )
        else:
            total_cut = rq

        new_alloc = qty_alloc - total_cut
        if new_alloc < shipped - 1e-9:
            conn.rollback()
            return False, "整合性エラー: 引当済が出荷済を下回るため中止しました"

        released_state = update_line_state(qty_req, new_alloc, shipped, hold_flag)
        cur.execute(
            "UPDATE order_lines SET qty_allocated = ?, state_code = ?, updated_at = ? WHERE line_id = ?",
            (new_alloc, released_state, datetime.now().isoformat(timespec="seconds"), line_id),
        )
        conn.commit()

    log_audit_event(
        event_type="RELEASE",
        user_id=(operator or "").strip() or None,
        order_id=order_id,
        order_no=order_ref,
        line_id=line_id,
        item_code=item_code,
        before_value={
            "qty_allocated": qty_alloc,
            "shipped_qty": shipped,
            "qty_unshipped": releasable,
        },
        after_value={
            "released_qty": float(total_cut),
            "qty_allocated": float(new_alloc),
            "qty_unshipped": float(new_alloc - shipped),
        },
        reason_code=reason_code or None,
        free_note=(free_note or "").strip() or None,
    )

    return True, f"引当を {total_cut:g} 解除しました（商品 {item_code}）"


def _get_line_allocation_breakdown(cur, line_id):
    cur.execute(
        """
        SELECT
            location_code,
            SUM(allocated_qty) AS allocated_qty,
            SUM(shipped_qty) AS shipped_qty
        FROM allocation_details
        WHERE line_id = ?
        GROUP BY location_code
        ORDER BY location_code
        """,
        (line_id,),
    )
    rows = []
    for r in cur.fetchall():
        alloc = float(r["allocated_qty"] or 0.0)
        shipped = float(r["shipped_qty"] or 0.0)
        rows.append(
            {
                "location_code": r["location_code"],
                "allocated_qty": alloc,
                "shipped_qty": shipped,
                "qty_unshipped": alloc - shipped,
            }
        )
    return rows


def reallocate_shortage_for_line(
    line_id,
    from_location,
    to_location,
    qty,
    changed_by=None,
    reason_code="RELOCATION",
):
    """
    同一 line_id 内で未出荷引当をロケ間で付け替える（総引当・出荷済は不変）。

    戻り値: (成功, メッセージ)
    """
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return False, "再引当数量が不正です"
    if q <= 0:
        return False, "再引当数量は0より大きくしてください"

    from_loc = (from_location or "").strip()
    to_loc = (to_location or "").strip()
    if not from_loc or not to_loc:
        return False, "再引当元/再引当先ロケーションを指定してください"
    if from_loc == to_loc:
        return False, "再引当元と再引当先は別ロケーションを指定してください"

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT l.line_id, l.order_id, l.item_code, l.qty_allocated, l.shipped_qty, o.reference
            FROM order_lines l
            JOIN orders o ON o.order_id = l.order_id
            WHERE l.line_id = ?
            """,
            (line_id,),
        )
        line = cur.fetchone()
        if not line:
            return False, "明細が見つかりません"

        before_breakdown = _get_line_allocation_breakdown(cur, line_id)

        cur.execute(
            """
            SELECT detail_id, allocated_qty, shipped_qty
            FROM allocation_details
            WHERE line_id = ? AND location_code = ?
            ORDER BY detail_id DESC
            LIMIT 1
            """,
            (line_id, from_loc),
        )
        from_detail = cur.fetchone()
        if not from_detail:
            return False, f"再引当元ロケーション {from_loc} の引当明細がありません"
        from_alloc = float(from_detail["allocated_qty"])
        from_shipped = float(from_detail["shipped_qty"])
        from_unshipped = from_alloc - from_shipped
        if q > from_unshipped + 1e-6:
            return False, f"再引当元ロケーションの未出荷引当は {from_unshipped:g} までです"

        # 再引当先の現在庫余力チェック（既存引当を差し引いた引当可能在庫）
        cur.execute(
            """
            SELECT COALESCE(SUM(
                CASE
                    WHEN tx_type IN ('receipt', 'move_in', 'count_plus') THEN qty
                    WHEN tx_type IN ('issue', 'move_out', 'count_minus') THEN -qty
                    ELSE 0
                END
            ), 0) AS stock_qty
            FROM inventory_transactions
            WHERE item_code = ? AND location_code = ?
            """,
            (line["item_code"], to_loc),
        )
        to_stock = float(cur.fetchone()["stock_qty"] or 0.0)
        cur.execute(
            """
            SELECT COALESCE(SUM(ad.allocated_qty - ad.shipped_qty), 0) AS reserved_qty
            FROM allocation_details ad
            JOIN order_lines ol ON ol.line_id = ad.line_id
            WHERE ol.item_code = ? AND ad.location_code = ?
            """,
            (line["item_code"], to_loc),
        )
        to_reserved = float(cur.fetchone()["reserved_qty"] or 0.0)
        to_allocatable = max(to_stock - to_reserved, 0.0)
        if q > to_allocatable + 1e-6:
            return (
                False,
                f"再引当先ロケーション {to_loc} の引当可能在庫が不足しています（可能 {to_allocatable:g}）",
            )

        new_from_alloc = from_alloc - q
        if new_from_alloc < from_shipped - 1e-9:
            conn.rollback()
            return False, "整合性エラー: 再引当元の allocated が shipped を下回るため中止しました"
        if new_from_alloc <= 1e-9 and from_shipped <= 1e-9:
            cur.execute("DELETE FROM allocation_details WHERE detail_id = ?", (from_detail["detail_id"],))
        else:
            cur.execute(
                "UPDATE allocation_details SET allocated_qty = ? WHERE detail_id = ?",
                (new_from_alloc, from_detail["detail_id"]),
            )

        cur.execute(
            """
            SELECT detail_id, allocated_qty
            FROM allocation_details
            WHERE line_id = ? AND location_code = ?
            ORDER BY detail_id DESC
            LIMIT 1
            """,
            (line_id, to_loc),
        )
        to_detail = cur.fetchone()
        if to_detail:
            cur.execute(
                "UPDATE allocation_details SET allocated_qty = ? WHERE detail_id = ?",
                (float(to_detail["allocated_qty"]) + q, to_detail["detail_id"]),
            )
        else:
            cur.execute(
                """
                INSERT INTO allocation_details (line_id, location_code, allocated_qty, shipped_qty)
                VALUES (?, ?, ?, 0)
                """,
                (line_id, to_loc, q),
            )

        # 総量整合チェック（order_lines の意味は変更しない）
        cur.execute(
            "SELECT COALESCE(SUM(allocated_qty), 0) AS total_alloc FROM allocation_details WHERE line_id = ?",
            (line_id,),
        )
        total_alloc = float(cur.fetchone()["total_alloc"] or 0.0)
        if abs(total_alloc - float(line["qty_allocated"])) > 1e-6:
            conn.rollback()
            return False, "整合性エラー: 再引当後のロケ別引当合計が明細引当合計と一致しません"
        cur.execute(
            "SELECT COALESCE(SUM(shipped_qty), 0) AS total_shipped FROM allocation_details WHERE line_id = ?",
            (line_id,),
        )
        total_shipped = float(cur.fetchone()["total_shipped"] or 0.0)
        if abs(total_shipped - float(line["shipped_qty"])) > 1e-6:
            conn.rollback()
            return False, "整合性エラー: 再引当後のロケ別出荷済合計が明細出荷済合計と一致しません"

        after_breakdown = _get_line_allocation_breakdown(cur, line_id)
        conn.commit()

    log_audit_event(
        event_type="REALLOCATE",
        user_id=changed_by,
        order_id=line["order_id"],
        order_no=line["reference"],
        line_id=line_id,
        item_code=line["item_code"],
        reason_code=reason_code or "RELOCATION",
        before_value={"from_location": from_loc, "to_location": to_loc, "qty": q, "details": before_breakdown},
        after_value={"from_location": from_loc, "to_location": to_loc, "qty": q, "details": after_breakdown},
        free_note="同一明細内の再引当",
    )
    return True, f"再引当を実行しました（line_id={line_id}, {from_loc} -> {to_loc}, qty={q:g}）"


def _row_to_dict(row):
    return dict(row) if row is not None else None


def _json_dump(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def get_reason_options():
    return REASON_LABELS.copy()


def get_reason_label(reason_code, default="-"):
    return REASON_LABELS.get(reason_code, reason_code or default)


def get_state_label(state_code):
    return STATE_LABELS.get(state_code, state_code or "-")


def get_approval_label(status_code):
    return APPROVAL_LABELS.get(status_code, status_code or "-")


def get_event_label(event_type, default="-"):
    return EVENT_LABELS.get(event_type, event_type or default)


def get_event_options():
    return list(EVENT_LABELS.keys())


def log_audit_event(
    event_type,
    user_id=None,
    role_name=None,
    warehouse_code=DEFAULT_WAREHOUSE_CODE,
    order_id=None,
    order_no=None,
    line_id=None,
    item_code=None,
    location_code=None,
    before_value=None,
    after_value=None,
    reason_code=None,
    free_note=None,
):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_logs (
                event_type,
                event_at,
                user_id,
                role_name,
                warehouse_code,
                order_id,
                order_no,
                line_id,
                item_code,
                location_code,
                before_value,
                after_value,
                reason_code,
                free_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                datetime.now().isoformat(timespec="seconds"),
                user_id,
                role_name,
                warehouse_code,
                order_id,
                order_no,
                line_id,
                item_code,
                location_code,
                _json_dump(before_value),
                _json_dump(after_value),
                reason_code,
                free_note,
            ),
        )
        conn.commit()


def get_recent_release_logs(limit=20):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                event_at,
                user_id,
                order_id,
                line_id,
                item_code,
                reason_code,
                free_note,
                before_value,
                after_value
            FROM audit_logs
            WHERE event_type = 'RELEASE'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def get_recent_ship_confirm_logs(limit=20):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                event_at,
                user_id,
                order_id,
                line_id,
                item_code,
                reason_code,
                free_note,
                before_value,
                after_value
            FROM audit_logs
            WHERE event_type = 'SHIP_CONFIRM'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def search_audit_logs(
    event_types=None,
    item_code=None,
    order_id=None,
    line_id=None,
    user_id=None,
    reason_code=None,
    keyword=None,
    limit=200,
):
    where = []
    params = []

    if event_types:
        if isinstance(event_types, str):
            event_types = [event_types]
        types = [t for t in event_types if t]
        if types:
            placeholders = ", ".join("?" for _ in types)
            where.append(f"event_type IN ({placeholders})")
            params.extend(types)

    if item_code:
        where.append("item_code = ?")
        params.append(item_code)
    if order_id is not None:
        where.append("order_id = ?")
        params.append(int(order_id))
    if line_id is not None:
        where.append("line_id = ?")
        params.append(int(line_id))
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if reason_code:
        where.append("reason_code = ?")
        params.append(reason_code)
    if keyword:
        like = f"%{keyword}%"
        where.append("(free_note LIKE ? OR before_value LIKE ? OR after_value LIKE ?)")
        params.extend([like, like, like])

    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = 200
    limit_value = max(1, min(limit_value, 500))

    sql = """
        SELECT
            id,
            event_type,
            event_at,
            user_id,
            role_name,
            warehouse_code,
            order_id,
            order_no,
            line_id,
            item_code,
            location_code,
            before_value,
            after_value,
            reason_code,
            free_note
        FROM audit_logs
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit_value)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


def try_parse_json_text(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _short_text(value, max_len=80):
    text = str(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


def _summarize_audit_value(value, list_label="list件数"):
    parsed = try_parse_json_text(value)
    if parsed is None:
        return "-"

    if isinstance(parsed, dict):
        summary = parsed.get("summary")
        if summary is not None:
            return _summarize_audit_value(summary, list_label="summary件数")

        if "lines" in parsed:
            return _summarize_audit_value(parsed.get("lines"))

        parts = []
        for key in [
            "released_qty",
            "total_ship_qty",
            "qty",
            "requested_ship_qty",
            "line_id",
            "item_code",
            "location_code",
            "from_location",
            "to_location",
            "state_code",
            "next_state",
            "qty_allocated",
            "qty_unshipped",
        ]:
            if key in parsed and parsed[key] not in (None, ""):
                parts.append(f"{key}={parsed[key]}")
        if parts:
            return _short_text(" / ".join(parts), 120)
        return "-"

    if isinstance(parsed, list):
        line_ids = []
        item_codes = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if item.get("line_id") is not None:
                line_ids.append(str(item["line_id"]))
            if item.get("item_code"):
                item_codes.append(str(item["item_code"]))

        parts = [f"{list_label}={len(parsed)}"]
        if line_ids:
            parts.append("line_id=" + ",".join(line_ids[:5]))
        if item_codes:
            parts.append("item=" + ",".join(sorted(set(item_codes))[:5]))
        return _short_text(" / ".join(parts), 120)

    return _short_text(parsed, 80)


def summarize_audit_log_row(row):
    d = dict(row)
    return {
        "event_at": d.get("event_at"),
        "event_type": d.get("event_type"),
        "user_id": d.get("user_id"),
        "order_id": d.get("order_id"),
        "line_id": d.get("line_id"),
        "item_code": d.get("item_code"),
        "location_code": d.get("location_code"),
        "reason_code": d.get("reason_code"),
        "free_note": d.get("free_note"),
        "before_summary": _summarize_audit_value(d.get("before_value")),
        "after_summary": _summarize_audit_value(d.get("after_value")),
    }


def infer_line_state(qty_required, qty_allocated, shipped_qty):
    req = float(qty_required or 0)
    alloc = float(qty_allocated or 0)
    shipped = float(shipped_qty or 0)

    if shipped >= req and req > 0:
        return "SHIPPED"
    if shipped > 0:
        return "PARTIAL_SHIPPED"
    if alloc >= req and req > 0:
        return "ALLOCATED"
    if alloc > 0:
        return "PARTIAL_ALLOCATED"
    return "UNALLOCATED"


def get_latest_line_state_map(order_id=None):
    with get_connection() as conn:
        cur = conn.cursor()
        params = []
        where = "WHERE line_id IS NOT NULL"
        if order_id is not None:
            where += " AND order_id = ?"
            params.append(order_id)

        cur.execute(
            f"""
            SELECT s.*
            FROM order_state_logs s
            INNER JOIN (
                SELECT line_id, MAX(id) AS max_id
                FROM order_state_logs
                {where}
                GROUP BY line_id
            ) latest
              ON latest.max_id = s.id
            ORDER BY s.line_id
            """,
            params,
        )
        rows = cur.fetchall()
        return {int(r["line_id"]): dict(r) for r in rows}


def get_line_impact_order_counts(order_id=None):
    with get_connection() as conn:
        cur = conn.cursor()
        params = []
        where = ""
        if order_id is not None:
            where = "WHERE l1.order_id = ?"
            params.append(order_id)
        cur.execute(
            f"""
            SELECT l1.line_id, COUNT(DISTINCT l2.order_id) AS impact_order_count
            FROM order_lines l1
            LEFT JOIN order_lines l2
              ON l1.item_code = l2.item_code
             AND l1.order_id <> l2.order_id
             AND l2.qty_allocated > l2.shipped_qty
            {where}
            GROUP BY l1.line_id
            """,
            params,
        )
        return {int(r["line_id"]): int(r["impact_order_count"] or 0) for r in cur.fetchall()}


def _build_line_state_rows(line_rows, state_map, impact_map):
    result = []
    for row in line_rows:
        line_id = int(row["line_id"])
        state_row = state_map.get(line_id, {})
        inferred_state = infer_line_state(
            row["qty_required"], row["qty_allocated"], row["shipped_qty"]
        )
        state_code = state_row.get("state_code") or inferred_state
        approval_status = state_row.get("approval_status") or "NOT_REQUIRED"
        item = {
            **row,
            "state_code": state_code,
            "state_label": get_state_label(state_code),
            "state_reason": state_row.get("state_reason"),
            "hold_flag": int(state_row.get("hold_flag") or 0),
            "hold_reason": state_row.get("hold_reason"),
            "approval_required": int(state_row.get("approval_required") or 0),
            "approval_status": approval_status,
            "approval_label": get_approval_label(approval_status),
            "impact_order_count": int(state_row.get("impact_order_count") or impact_map.get(line_id, 0)),
            "changed_by": state_row.get("changed_by"),
            "changed_at": state_row.get("changed_at"),
        }
        result.append(item)
    return result


def get_all_line_state_rows():
    """
    全出荷明細を横断し、数量事実 + 最新状態を line 単位で返す。

    例外影響あり件数は暫定的に impact_order_count > 0 を基準に扱う。
    将来はより明示的な例外フラグへ寄せる余地あり。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                l.order_id,
                o.reference,
                l.line_id,
                l.item_code,
                l.qty_required,
                l.qty_allocated,
                l.shipped_qty,
                (l.qty_allocated - l.shipped_qty) AS qty_unshipped
            FROM order_lines l
            JOIN orders o ON o.order_id = l.order_id
            ORDER BY l.order_id DESC, l.line_id
            """
        )
        line_rows = [dict(r) for r in cur.fetchall()]

    state_map = get_latest_line_state_map()
    impact_map = get_line_impact_order_counts()
    return _build_line_state_rows(line_rows, state_map, impact_map)


def get_line_state_history(line_id, limit=50):
    """
    指定明細の状態履歴を新しい順で返す。

    状態履歴が未登録でも数量事実は order_lines 側に残るため、
    0件は異常ではなく「未記録」として扱う前提。
    """
    try:
        line_id_value = int(line_id)
    except (TypeError, ValueError):
        return []

    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = 50
    limit_value = max(1, min(limit_value, 500))

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                s.id,
                s.order_id,
                o.reference,
                s.line_id,
                l.item_code,
                l.qty_required,
                l.qty_allocated,
                l.shipped_qty,
                (l.qty_allocated - l.shipped_qty) AS qty_unshipped,
                s.state_code,
                s.state_reason,
                s.hold_flag,
                s.hold_reason,
                s.approval_required,
                s.approval_status,
                s.impact_order_count,
                s.changed_by,
                s.changed_at,
                s.free_note
            FROM order_state_logs s
            LEFT JOIN orders o ON o.order_id = s.order_id
            LEFT JOIN order_lines l ON l.line_id = s.line_id
            WHERE s.line_id = ?
            ORDER BY s.id DESC
            LIMIT ?
            """,
            (line_id_value, limit_value),
        )
        return cur.fetchall()


def get_line_state_summary(rows=None):
    if rows is None:
        rows = get_all_line_state_rows()

    return {
        "hold_count": sum(1 for row in rows if int(row.get("hold_flag") or 0) == 1),
        "realloc_pending_count": sum(
            1 for row in rows if row.get("state_code") == "REALLOC_PENDING"
        ),
        "approval_waiting_count": sum(
            1
            for row in rows
            if int(row.get("approval_required") or 0) == 1
            and row.get("approval_status") == "WAITING"
        ),
        "partial_shipped_count": sum(
            1 for row in rows if row.get("state_code") == "PARTIAL_SHIPPED"
        ),
        "impacted_exception_count": sum(
            1 for row in rows if int(row.get("impact_order_count") or 0) > 0
        ),
    }


def save_line_state(
    line_id,
    state_code,
    state_reason=None,
    hold_flag=False,
    hold_reason=None,
    approval_required=False,
    approval_status="NOT_REQUIRED",
    impact_order_count=0,
    changed_by=None,
    free_note=None,
):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT l.line_id, l.order_id, o.reference, l.item_code,
                   l.qty_required, l.qty_allocated, l.shipped_qty
            FROM order_lines l
            JOIN orders o ON o.order_id = l.order_id
            WHERE l.line_id = ?
            """,
            (line_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, "明細が見つかりません"

        state_reason = state_reason or None
        approval_status = approval_status or "NOT_REQUIRED"
        hold_flag_int = int(bool(hold_flag))
        hold_reason = hold_reason if hold_flag_int else None

        cur.execute(
            """
            SELECT state_code, state_reason, hold_flag, hold_reason, approval_required, approval_status
            FROM order_state_logs
            WHERE line_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (line_id,),
        )
        latest_state = cur.fetchone()
        if latest_state:
            latest_key = (
                latest_state["state_code"],
                latest_state["state_reason"] or None,
                int(latest_state["hold_flag"] or 0),
                latest_state["approval_status"] or "NOT_REQUIRED",
            )
            next_key = (
                state_code,
                state_reason,
                hold_flag_int,
                approval_status,
            )
            if latest_key == next_key:
                return True, "変更なしです"

        before_state = {
            "inferred_state": infer_line_state(
                row["qty_required"], row["qty_allocated"], row["shipped_qty"]
            )
        }
        after_state = {
            "state_code": state_code,
            "state_reason": state_reason,
            "hold_flag": hold_flag_int,
            "hold_reason": hold_reason,
            "approval_required": int(bool(approval_required)),
            "approval_status": approval_status,
            "impact_order_count": int(impact_order_count or 0),
            "changed_by": changed_by,
        }

        changed_at = datetime.now().isoformat(timespec="seconds")
        cur.execute(
            """
            INSERT INTO order_state_logs (
                order_id,
                line_id,
                state_code,
                state_reason,
                hold_flag,
                hold_reason,
                approval_required,
                approval_status,
                impact_order_count,
                changed_by,
                changed_at,
                free_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["order_id"],
                row["line_id"],
                state_code,
                state_reason,
                hold_flag_int,
                hold_reason,
                int(bool(approval_required)),
                approval_status,
                int(impact_order_count or 0),
                changed_by,
                changed_at,
                free_note,
            ),
        )
        conn.commit()

    log_audit_event(
        event_type="STATE_CHANGE",
        user_id=changed_by,
        order_id=row["order_id"],
        order_no=row["reference"],
        line_id=row["line_id"],
        item_code=row["item_code"],
        before_value=before_state,
        after_value=after_state,
        reason_code=state_reason,
        free_note=free_note,
    )
    return True, "状態を保存しました"


def get_current_stock_breakdown():
    stock_rows = [dict(r) for r in get_current_stock()]
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                ol.item_code,
                ad.location_code,
                COALESCE(SUM(ad.allocated_qty - ad.shipped_qty), 0) AS reserved_qty
            FROM allocation_details ad
            JOIN order_lines ol ON ol.line_id = ad.line_id
            GROUP BY ol.item_code, ad.location_code
            """
        )
        reserved_map = {
            (r["item_code"], r["location_code"]): float(r["reserved_qty"])
            for r in cur.fetchall()
        }

        cur.execute(
            """
            SELECT t1.item_code, t1.location_code, t1.operator, t1.tx_time, t1.tx_type
            FROM inventory_transactions t1
            INNER JOIN (
                SELECT item_code, location_code, MAX(tx_id) AS max_tx_id
                FROM inventory_transactions
                GROUP BY item_code, location_code
            ) t2 ON t2.max_tx_id = t1.tx_id
            """
        )
        latest_tx_map = {
            (r["item_code"], r["location_code"]): dict(r)
            for r in cur.fetchall()
        }

    result = []
    for row in stock_rows:
        item_code = row["item_code"]
        location_code = row["location_code"]
        total_qty = float(row["stock_qty"])
        allocated_qty = float(reserved_map.get((item_code, location_code), 0.0))
        latest_tx = latest_tx_map.get((item_code, location_code), {})
        tx_type = latest_tx.get("tx_type")

        result.append(
            {
                "item_code": item_code,
                "location_code": location_code,
                "total_qty": total_qty,
                "allocated_qty": allocated_qty,
                "allocatable_qty": max(total_qty - allocated_qty, 0.0),
                "hold_qty": 0.0,
                "diff_flag": 1 if tx_type in ("count_plus", "count_minus") else 0,
                "exception_flag": 1 if allocated_qty > total_qty else 0,
                "location_type": "通常",
                "warehouse_code": DEFAULT_WAREHOUSE_CODE,
                "changed_by": latest_tx.get("operator"),
                "changed_at": latest_tx.get("tx_time"),
            }
        )
    return result


def get_allocatable_stock_by_item_enhanced():
    base_rows = get_allocatable_stock_by_item()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT item_code, COUNT(DISTINCT order_id) AS inuse_order_count
            FROM order_lines
            WHERE qty_allocated > shipped_qty
            GROUP BY item_code
            """
        )
        inuse_map = {r["item_code"]: int(r["inuse_order_count"]) for r in cur.fetchall()}

    result = []
    for row in base_rows:
        item_code = row["item_code"]
        result.append(
            {
                **row,
                "hold_qty": 0.0,
                "inuse_order_count": int(inuse_map.get(item_code, 0)),
                "priority_reserved_qty": 0.0,
                "inbound_planned_qty": 0.0,
                "warehouse_code": DEFAULT_WAREHOUSE_CODE,
            }
        )
    return result


def get_enhanced_order_lines(order_id):
    line_rows = [dict(r) for r in get_order_lines_shipment_view(order_id)]
    state_map = get_latest_line_state_map(order_id)
    impact_map = get_line_impact_order_counts(order_id)
    return _build_line_state_rows(line_rows, state_map, impact_map)


def get_shipment_blockers(order_id, line_ship_qty_map, reason_code=None):
    blockers = []
    line_rows = get_enhanced_order_lines(order_id)
    line_map = {int(r["line_id"]): r for r in line_rows}

    # 状態ベースの停止条件
    for line_id, row in line_map.items():
        requested = float(line_ship_qty_map.get(line_id, 0.0) or 0.0)
        if requested <= 0:
            continue
        if int(row.get("hold_flag") or 0) == 1:
            blockers.append(f"明細 {line_id}: 保留中のため出荷確定できません")
        if int(row.get("approval_required") or 0) == 1 and row.get("approval_status") != "APPROVED":
            blockers.append(f"明細 {line_id}: 承認待ちのため出荷確定できません")

    # ロケーション現在庫ベースの不足チェック
    current_stock_map = {
        (r["item_code"], r["location_code"]): float(r["stock_qty"])
        for r in get_current_stock()
    }
    ad_rows = [dict(r) for r in get_allocation_details_for_order(order_id)]
    grouped = {}
    for row in ad_rows:
        grouped.setdefault(int(row["line_id"]), []).append(row)

    consumed_map = defaultdict(float)
    for line_id, details in grouped.items():
        requested = float(line_ship_qty_map.get(line_id, 0.0) or 0.0)
        if requested <= 0:
            continue
        remain = requested
        for det in details:
            if remain <= 1e-9:
                break
            key = (det["item_code"], det["location_code"])
            now_stock = float(current_stock_map.get(key, 0.0)) - float(consumed_map.get(key, 0.0))
            detail_unshipped = float(det["qty_unshipped"])
            to_ship = min(remain, detail_unshipped)
            if to_ship > now_stock + 1e-9:
                blockers.append(
                    f"明細 {line_id}: ロケーション {det['location_code']} の現在庫不足です（必要 {to_ship:g} / 現在庫 {max(now_stock, 0):g}）"
                )
            consumed_map[key] += max(min(to_ship, now_stock), 0.0)
            remain -= to_ship

    if any(float(v or 0.0) > 0 for v in line_ship_qty_map.values()) and not reason_code:
        blockers.append("出荷理由コードを選択してください")

    return blockers


def get_shortage_candidates_for_order(order_id, line_ship_qty_map):
    """
    出荷確定時のロケーション在庫不足候補を構造化して返す。

    各要素:
      - line_id
      - item_code
      - location_code
      - requested_qty
      - current_stock
      - shortage_qty
    """
    shortages = []
    current_stock_map = {
        (r["item_code"], r["location_code"]): float(r["stock_qty"])
        for r in get_current_stock()
    }
    ad_rows = [dict(r) for r in get_allocation_details_for_order(order_id)]
    grouped = {}
    for row in ad_rows:
        grouped.setdefault(int(row["line_id"]), []).append(row)

    consumed_map = defaultdict(float)
    for line_id, details in grouped.items():
        requested = float(line_ship_qty_map.get(line_id, 0.0) or 0.0)
        if requested <= 0:
            continue
        remain = requested
        for det in details:
            if remain <= 1e-9:
                break
            key = (det["item_code"], det["location_code"])
            now_stock = float(current_stock_map.get(key, 0.0)) - float(consumed_map.get(key, 0.0))
            detail_unshipped = float(det["qty_unshipped"])
            to_ship = min(remain, detail_unshipped)
            if to_ship > now_stock + 1e-9:
                current_stock = max(now_stock, 0.0)
                shortage = max(to_ship - current_stock, 0.0)
                shortages.append(
                    {
                        "line_id": int(line_id),
                        "item_code": det["item_code"],
                        "location_code": det["location_code"],
                        "requested_qty": float(to_ship),
                        "current_stock": float(current_stock),
                        "shortage_qty": float(shortage),
                    }
                )
            consumed_map[key] += max(min(to_ship, now_stock), 0.0)
            remain -= to_ship
    return shortages


def get_all_items() -> list[dict]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT item_code, item_name, unit, is_active FROM items ORDER BY item_code"
        )
        return [dict(r) for r in cur.fetchall()]


def register_item(item_code: str, item_name: str, unit: str, is_active: int = 1) -> str | None:
    """商品を登録する。重複時は None を返す。成功時は item_code を返す。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM items WHERE item_code = ?", (item_code,))
        if cur.fetchone():
            return None
        cur.execute(
            "INSERT INTO items (item_code, item_name, unit, is_active) VALUES (?, ?, ?, ?)",
            (item_code, item_name, unit, is_active),
        )
        conn.commit()
    return item_code


def update_item_status(item_code: str, is_active: int) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE items SET is_active = ? WHERE item_code = ?",
            (is_active, item_code),
        )
        conn.commit()


def get_release_blockers(
    line_id,
    reason_code=None,
    approval_required=False,
    approval_status="NOT_REQUIRED",
    free_note=None,
):
    blockers = []
    if not reason_code:
        blockers.append("解除理由コードを選択してください")
    if reason_code == "OTHER" and not (free_note or "").strip():
        blockers.append("解除理由がその他の場合は自由記述を入力してください")
    if approval_required and approval_status != "APPROVED":
        blockers.append("承認待ちのため解除できません")
    return blockers
