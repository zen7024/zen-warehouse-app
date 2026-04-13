import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "warehouse.db"

# 引当明細が無い旧データ向けの出庫ロケーション（新規引当は allocation_details で実ロケーションへ記録）
SHIP_ISSUE_LOCATION = "__SHIP__"


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
    引当はロケーション別に allocation_details へ記録する（同一商品は location_code 昇順で消費＝最小 FIFO）。

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

        remaining = defaultdict(lambda: defaultdict(float))
        for row in _fetch_current_stock_rows(cur):
            d = dict(row)
            remaining[d["item_code"]][d["location_code"]] += float(d["stock_qty"])

        cur.execute("""
        SELECT ol.item_code, ad.location_code,
               COALESCE(SUM(ad.allocated_qty - ad.shipped_qty), 0) AS reserved
        FROM allocation_details ad
        JOIN order_lines ol ON ol.line_id = ad.line_id
        GROUP BY ol.item_code, ad.location_code
        """)
        for r in cur.fetchall():
            item_code = r["item_code"]
            loc = r["location_code"]
            res = float(r["reserved"])
            remaining[item_code][loc] = remaining[item_code].get(loc, 0.0) - res
            if remaining[item_code][loc] < 0:
                remaining[item_code][loc] = 0.0

        cur.execute(
            "INSERT INTO orders (reference, note) VALUES (?, ?)",
            (reference or None, note or None),
        )
        order_id = cur.lastrowid
        results = []

        for item_code, req in prepared:
            need = req
            details_to_insert = []
            locs = sorted(remaining[item_code].keys())
            for loc in locs:
                if need <= 0:
                    break
                avail = max(0.0, remaining[item_code].get(loc, 0.0))
                if avail <= 0:
                    continue
                take = min(need, avail)
                details_to_insert.append((loc, take))
                remaining[item_code][loc] -= take
                need -= take

            alloc = req - need

            cur.execute("""
            INSERT INTO order_lines (order_id, item_code, qty_required, qty_allocated)
            VALUES (?, ?, ?, ?)
            """, (order_id, item_code, req, alloc))
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
            (l.qty_required - l.qty_allocated) AS qty_pending
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
        SELECT line_id, item_code, qty_allocated, shipped_qty
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
            qty_alloc = float(line["qty_allocated"])
            shipped_line = float(line["shipped_qty"])
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

                cur.execute(
                    "UPDATE order_lines SET shipped_qty = ? WHERE line_id = ?",
                    (shipped_line + requested, line_id),
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
                cur.execute(
                    "UPDATE order_lines SET shipped_qty = ? WHERE line_id = ?",
                    (shipped_line + requested, line_id),
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


def release_allocation_for_line(line_id, release_qty):
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
        SELECT order_id, item_code, qty_required, qty_allocated, shipped_qty
        FROM order_lines
        WHERE line_id = ?
        """, (line_id,))
        line = cur.fetchone()
        if not line:
            return False, "明細が見つかりません"

        qty_alloc = float(line["qty_allocated"])
        shipped = float(line["shipped_qty"])
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

        cur.execute(
            "UPDATE order_lines SET qty_allocated = ? WHERE line_id = ?",
            (new_alloc, line_id),
        )
        conn.commit()

    return True, f"引当を {total_cut:g} 解除しました（商品 {line['item_code']}）"