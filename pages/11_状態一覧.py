import pandas as pd
import streamlit as st

from core.db import (
    get_all_line_state_rows,
    get_approval_label,
    get_line_state_history,
    get_line_state_summary,
    get_reason_label,
    get_state_label,
    init_db,
)

init_db()
DETAIL_PAGE_PATHS = {
    "audit_log": "pages/10_監査ログ.py",
    "ship_confirm": "pages/8_出荷確定.py",
    "release": "pages/9_引当解除.py",
}
SHIP_CONFIRM_ALLOWED_STATES = {
    "PARTIAL_ALLOCATED",
    "ALLOCATED",
    "WORKING",
    "PARTIAL_SHIPPED",
}
RELEASE_ALLOWED_STATES = {
    "PARTIAL_ALLOCATED",
    "ALLOCATED",
    "REALLOC_PENDING",
    "PARTIAL_SHIPPED",
    "HOLD",
}
OPERATION_HIDDEN_STATES = {
    "UNALLOCATED",
    "RELEASED",
    "SHIPPED",
    "SENT_BACK",
    "CANCELLED",
}


def _display_text(value, default="-"):
    text = str(value).strip() if value is not None else ""
    return text or default


def _format_event_at(value):
    text = _display_text(value)
    if text == "-":
        return "-"
    return text.replace("T", " ")


def _approval_required_label(value):
    return "要" if int(value or 0) == 1 else "-"


def _build_detail_target(page, row):
    return {
        "source_page": "state_list",
        "target_page": page,
        "order_id": int(row["order_id"]),
        "line_id": int(row["line_id"]),
        "item_code": row.get("item_code"),
        "state_code": row.get("state_code"),
    }


def _get_selected_row(selection_event, rows):
    if not isinstance(selection_event, dict):
        return None
    selected_indexes = selection_event.get("selection", {}).get("rows", [])
    if not selected_indexes:
        return None
    selected_index = selected_indexes[0]
    if 0 <= selected_index < len(rows):
        return rows[selected_index]
    return None


def _can_show_ship_confirm(row):
    return (
        row.get("state_code") not in OPERATION_HIDDEN_STATES
        and float(row.get("qty_unshipped") or 0) > 0
        and int(row.get("hold_flag") or 0) == 0
        and row.get("approval_status") in {"NOT_REQUIRED", "APPROVED"}
        and row.get("state_code") in SHIP_CONFIRM_ALLOWED_STATES
    )


def _can_show_release(row):
    return (
        row.get("state_code") not in OPERATION_HIDDEN_STATES
        and float(row.get("qty_unshipped") or 0) > 0
        and row.get("state_code") in RELEASE_ALLOWED_STATES
    )


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
selection_event = None
try:
    selection_event = st.dataframe(
        df[display_cols],
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
except TypeError:
    st.dataframe(df[display_cols], width="stretch")

selected_row = _get_selected_row(selection_event, filtered_rows)

if selected_row is None:
    select_options = {
        f"指示ID {row['order_id']} / 明細ID {row['line_id']} / 商品 {row['item_code']}": row
        for row in filtered_rows
    }
    selected_label = st.selectbox(
        "詳細確認対象",
        options=[""] + list(select_options.keys()),
        index=0,
        placeholder="行を選んで監査ログへ進む",
    )
    if selected_label:
        selected_row = select_options[selected_label]

if selected_row is not None:
    st.caption(
        "選択中: "
        f"指示ID {selected_row['order_id']} / 明細ID {selected_row['line_id']} / "
        f"商品コード {_display_text(selected_row.get('item_code'))}"
    )
    st.subheader("状態履歴")
    history_rows = get_line_state_history(selected_row["line_id"])
    if not history_rows:
        st.info(
            "この明細には明示的な状態履歴がまだありません。"
            "現在の状態表示は数量事実からの推定を含む可能性があります。"
        )
    else:
        history_display_rows = []
        for history_row in history_rows:
            history_display_rows.append(
                {
                    "更新日時": _format_event_at(history_row["changed_at"]),
                    "状態": get_state_label(history_row["state_code"]),
                    "状態理由": get_reason_label(history_row["state_reason"]),
                    "保留": "はい" if int(history_row["hold_flag"] or 0) == 1 else "-",
                    "保留理由": _display_text(history_row["hold_reason"]),
                    "承認要否": _approval_required_label(history_row["approval_required"]),
                    "承認状態": get_approval_label(history_row["approval_status"]),
                    "影響案件数": int(history_row["impact_order_count"] or 0),
                    "更新者": _display_text(history_row["changed_by"]),
                    "自由記述": _display_text(history_row["free_note"]),
                }
            )
        history_df = pd.DataFrame(history_display_rows)
        st.dataframe(
            history_df[
                [
                    "更新日時",
                    "状態",
                    "状態理由",
                    "保留",
                    "保留理由",
                    "承認要否",
                    "承認状態",
                    "影響案件数",
                    "更新者",
                    "自由記述",
                ]
            ],
            width="stretch",
            hide_index=True,
        )
    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("監査ログで確認", type="primary"):
            st.session_state["detail_target"] = _build_detail_target("audit_log", selected_row)
            st.switch_page(DETAIL_PAGE_PATHS["audit_log"])
    with action_cols[1]:
        if _can_show_ship_confirm(selected_row):
            if st.button("出荷確定へ"):
                st.session_state["detail_target"] = _build_detail_target("ship_confirm", selected_row)
                st.switch_page(DETAIL_PAGE_PATHS["ship_confirm"])
    with action_cols[2]:
        if _can_show_release(selected_row):
            if st.button("引当解除へ"):
                st.session_state["detail_target"] = _build_detail_target("release", selected_row)
                st.switch_page(DETAIL_PAGE_PATHS["release"])
