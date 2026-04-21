import pandas as pd
import streamlit as st

from core.db import (
    get_all_line_state_rows,
    get_approval_label,
    get_line_state_summary,
    get_reason_label,
    get_state_label,
    init_db,
)

init_db()


def _display_text(value, default="-"):
    text = str(value).strip() if value is not None else ""
    return text or default


def _format_event_at(value):
    text = _display_text(value)
    if text == "-":
        return "-"
    return text.replace("T", " ")


st.title("📋 状態一覧")
st.write("今どの案件がどう止まっているかを、出荷明細単位で横断確認します。")
st.caption("数量の事実と業務状態を分けたまま、最新状態だけを一覧表示します。")

rows = get_all_line_state_rows()
state_options = sorted({row["state_code"] for row in rows if row.get("state_code")})
approval_options = sorted({row["approval_status"] for row in rows if row.get("approval_status")})

with st.expander("絞り込み条件", expanded=True):
    selected_states = st.multiselect(
        "状態",
        options=state_options,
        format_func=get_state_label,
        default=[],
        placeholder="未選択で全状態",
    )
    selected_approval_statuses = st.multiselect(
        "承認状態",
        options=approval_options,
        format_func=get_approval_label,
        default=[],
        placeholder="未選択で全承認状態",
    )
    hold_only = st.checkbox("保留のみ表示")

    c1, c2, c3 = st.columns(3)
    with c1:
        item_code_filter = st.text_input("商品コード", value="", placeholder="例: ITEM-001")
    with c2:
        order_id_filter = st.text_input("指示ID", value="", placeholder="例: 1001")
    with c3:
        user_filter = st.text_input("更新者", value="", placeholder="例: zen")

filtered_rows = rows
if selected_states:
    selected_state_set = set(selected_states)
    filtered_rows = [row for row in filtered_rows if row.get("state_code") in selected_state_set]
if selected_approval_statuses:
    selected_approval_set = set(selected_approval_statuses)
    filtered_rows = [
        row for row in filtered_rows if row.get("approval_status") in selected_approval_set
    ]
if hold_only:
    filtered_rows = [row for row in filtered_rows if int(row.get("hold_flag") or 0) == 1]
if item_code_filter.strip():
    needle = item_code_filter.strip().lower()
    filtered_rows = [
        row for row in filtered_rows if needle in str(row.get("item_code") or "").lower()
    ]
if order_id_filter.strip():
    filtered_rows = [
        row for row in filtered_rows if str(row.get("order_id") or "") == order_id_filter.strip()
    ]
if user_filter.strip():
    user_needle = user_filter.strip().lower()
    filtered_rows = [
        row for row in filtered_rows if user_needle in str(row.get("changed_by") or "").lower()
    ]

summary = get_line_state_summary(filtered_rows)
metric_cols = st.columns(5)
metric_cols[0].metric("保留件数", summary["hold_count"])
metric_cols[1].metric("再引当待ち件数", summary["realloc_pending_count"])
metric_cols[2].metric("承認待ち件数", summary["approval_waiting_count"])
metric_cols[3].metric("一部出荷件数", summary["partial_shipped_count"])
metric_cols[4].metric("例外影響あり件数", summary["impacted_exception_count"])
st.caption(f"件数サマリは現在の絞り込み結果に対する集計です。表示件数: {len(filtered_rows)}")

if not filtered_rows:
    st.info("条件に一致する状態データはありません。")
    st.stop()

display_rows = []
for row in filtered_rows:
    display_rows.append(
        {
            "指示ID": _display_text(row.get("order_id")),
            "出荷指示番号": _display_text(row.get("reference") or "(番号なし)"),
            "明細ID": _display_text(row.get("line_id")),
            "商品コード": _display_text(row.get("item_code")),
            "必要数": float(row.get("qty_required") or 0),
            "引当済数量": float(row.get("qty_allocated") or 0),
            "出荷済数量": float(row.get("shipped_qty") or 0),
            "未出荷数量": float(row.get("qty_unshipped") or 0),
            "状態": get_state_label(row.get("state_code")),
            "状態理由": get_reason_label(row.get("state_reason")),
            "保留": "はい" if int(row.get("hold_flag") or 0) == 1 else "-",
            "承認状態": get_approval_label(row.get("approval_status")),
            "影響案件数": int(row.get("impact_order_count") or 0),
            "更新者": _display_text(row.get("changed_by")),
            "更新日時": _format_event_at(row.get("changed_at")),
        }
    )

df = pd.DataFrame(display_rows)
display_cols = [
    "指示ID",
    "出荷指示番号",
    "明細ID",
    "商品コード",
    "必要数",
    "引当済数量",
    "出荷済数量",
    "未出荷数量",
    "状態",
    "状態理由",
    "保留",
    "承認状態",
    "影響案件数",
    "更新者",
    "更新日時",
]
st.dataframe(df[display_cols], width="stretch")
