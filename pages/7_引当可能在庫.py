import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    get_allocatable_stock_by_item_enhanced,
    get_allocatable_stock_by_item,
    get_order_competition_by_item,
    build_alloc_status,
    log_audit_event,
)

init_db()


def _competition_display_rows(rows):
    out = []
    for r in rows:
        ref = (r.get("reference") or "").strip() or "(番号なし)"
        out.append(
            {
                "出荷指示番号": ref,
                "明細ID": int(r["line_id"]),
                "必要数": float(r["qty_required"]),
                "引当済": float(r["qty_allocated"]),
                "出荷済": float(r["shipped_qty"]),
                "未引当": float(r["qty_pending"]),
                "未出荷引当": float(r["qty_unshipped"]),
                "引当状態": r.get("alloc_status")
                or build_alloc_status(r["qty_required"], r["qty_allocated"]),
            }
        )
    return out


st.title("📊 引当可能在庫（P0最小共通基盤版）")
st.write(
    "物理在庫から既存の未出荷引当を差し引き、さらに保留在庫・使用中案件数の見え方を足します。"
)

viewer_name = st.text_input("閲覧者", value="zen")
warehouse_code = st.selectbox("倉庫", ["WH-001"], index=0)
show_hold = st.checkbox("保留在庫を含めて表示", value=True)
show_inbound = st.checkbox("未入荷予定の参考表示を出す", value=True)

rows = get_allocatable_stock_by_item_enhanced()
if rows:
    df = pd.DataFrame(rows)
    if not show_hold:
        df = df[df["hold_qty"] <= 0]

    if show_inbound:
        df["inbound_planned_qty"] = df["inbound_planned_qty"].fillna(0)
    else:
        df["inbound_planned_qty"] = "-"

    df = df.rename(
        columns={
            "item_code": "商品コード",
            "physical_qty": "物理在庫",
            "allocated_qty": "未出荷引当",
            "allocatable_qty": "引当可能在庫",
            "hold_qty": "保留在庫",
            "inuse_order_count": "使用中案件数",
            "priority_reserved_qty": "優先予約数",
            "inbound_planned_qty": "未入荷予定",
            "warehouse_code": "倉庫コード",
        }
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("商品コード数", len(df))
    col2.metric("引当可能合計", f"{df['引当可能在庫'].replace('-', 0).astype(float).sum():g}")
    col3.metric("未出荷引当合計", f"{df['未出荷引当'].replace('-', 0).astype(float).sum():g}")
    st.dataframe(df, width="stretch")

    log_audit_event(
        event_type="VIEW_ALLOCATABLE_STOCK",
        user_id=viewer_name.strip() or None,
        warehouse_code=warehouse_code,
        after_value={
            "show_hold": show_hold,
            "show_inbound": show_inbound,
            "row_count": len(df),
        },
    )
else:
    st.info("物理在庫も引当明細もまだありません")

st.divider()
st.subheader("案件横断の使用中一覧")
st.caption("引当可能在庫が 0 に近い理由や、同一商品の他案件の取り合いを確認できます。")
candidates = get_allocatable_stock_by_item()
codes = sorted({r["item_code"] for r in candidates}) if candidates else []
if not codes:
    st.info("案件一覧を表示する商品コードがありません（物理在庫または未出荷引当のある商品が必要です）。")
else:
    pick = st.selectbox("商品コード", options=codes, key="alloc_stock_competition_item")
    comp = get_order_competition_by_item(pick)
    disp = _competition_display_rows(comp)
    if not disp:
        st.info("この商品コードの出荷明細はまだありません。")
    else:
        st.dataframe(pd.DataFrame(disp), width="stretch")
