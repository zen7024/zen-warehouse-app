import streamlit as st
import pandas as pd
from core.db import (
    DEFAULT_WAREHOUSE_CODE,
    get_current_stock_breakdown,
    get_user_warehouses,
    init_db,
    log_audit_event,
)

init_db()

st.title("📦 現在庫")
st.write("在庫イベントから集計した現在庫を、P0最小共通基盤の見え方で表示します。")

username = st.session_state.get("current_user") or st.session_state.get("username")
warehouse_rows = get_user_warehouses(username) if username else []
warehouse_codes = [row["warehouse_code"] for row in warehouse_rows] or [DEFAULT_WAREHOUSE_CODE]
if st.session_state.get("current_warehouse") not in warehouse_codes:
    st.session_state["current_warehouse"] = warehouse_codes[0]
warehouse_labels = {
    row["warehouse_code"]: f'{row["warehouse_code"]} | {row["warehouse_name"]}'
    for row in warehouse_rows
}
warehouse_code = st.selectbox(
    "倉庫",
    warehouse_codes,
    index=warehouse_codes.index(st.session_state["current_warehouse"]),
    format_func=lambda code: warehouse_labels.get(code, code),
)
st.session_state["current_warehouse"] = warehouse_code
st.caption(f"表示中の倉庫: {warehouse_labels.get(warehouse_code, warehouse_code)}")
show_exception_only = st.checkbox("例外ありのみ表示")
show_diff_only = st.checkbox("差異中のみ表示")
item_filter = st.text_input("商品コードフィルタ（部分一致）", value="")
location_filter = st.text_input("ロケーションフィルタ（部分一致）", value="")
viewer_name = st.text_input("閲覧者", value=username or "zen")

rows = get_current_stock_breakdown(warehouse_code=warehouse_code)

df = pd.DataFrame(rows)
if df.empty:
    st.info("現在庫データはまだありません")
    st.stop()

df = df.rename(
    columns={
        "item_code": "商品コード",
        "location_code": "ロケーション",
        "total_qty": "現在庫数",
        "allocated_qty": "引当済数量",
        "allocatable_qty": "引当可能在庫",
        "hold_qty": "保留",
        "diff_flag": "差異中",
        "exception_flag": "例外中",
        "location_type": "ロケ種別",
        "warehouse_code": "倉庫コード",
        "changed_by": "更新者",
        "changed_at": "更新日時",
    }
)

if "ロケーション" in df.columns:
    df = df[df["ロケーション"] != "__SHIP__"]

if show_exception_only and "例外中" in df.columns:
    df = df[df["例外中"] == 1]
if show_diff_only and "差異中" in df.columns:
    df = df[df["差異中"] == 1]
if item_filter.strip() and "商品コード" in df.columns:
    needle = item_filter.strip().lower()
    df = df[df["商品コード"].astype(str).str.lower().str.contains(needle)]
if location_filter.strip() and "ロケーション" in df.columns:
    loc_needle = location_filter.strip().lower()
    df = df[df["ロケーション"].astype(str).str.lower().str.contains(loc_needle)]

col1, col2 = st.columns(2)
col1.metric("在庫明細数", len(df))
if "現在庫数" in df.columns:
    col2.metric("現在庫数合計", f"{df['現在庫数'].sum():g}")


def highlight_flags(row):
    styles = ["" for _ in row]
    columns = list(row.index)
    if "例外中" in columns and row.get("例外中") == 1:
        styles[columns.index("例外中")] = "background-color:#ffe0b2"
    if "差異中" in columns and row.get("差異中") == 1:
        styles[columns.index("差異中")] = "background-color:#ffcdd2"
    return styles


display_cols = [
    "商品コード",
    "ロケーション",
    "現在庫数",
    "引当済数量",
    "引当可能在庫",
    "保留",
    "ロケ種別",
    "倉庫コード",
    "差異中",
    "例外中",
    "更新者",
    "更新日時",
]
display_cols = [col for col in display_cols if col in df.columns]
st.dataframe(df[display_cols].style.apply(highlight_flags, axis=1), use_container_width=True)

log_audit_event(
    event_type="VIEW_CURRENT_STOCK",
    user_id=viewer_name.strip() or None,
    warehouse_code=warehouse_code,
    after_value={
        "show_exception_only": show_exception_only,
        "show_diff_only": show_diff_only,
        "row_count": len(df),
    },
)
