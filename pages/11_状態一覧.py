import hashlib

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
FILTER_STATE_KEY = "state_list_filters"
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
ROUTE_BUTTON_LABELS = {
    "audit_log": "監査ログで履歴確認",
    "ship_confirm": "出荷確定で確認",
    "release": "引当解除で確認",
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


def _state_note(row):
    state_code = row.get("state_code")
    qty_unshipped = float(row.get("qty_unshipped") or 0)
    shipped_qty = float(row.get("shipped_qty") or 0)
    if state_code == "PARTIAL_SHIPPED" and shipped_qty > 0 and qty_unshipped > 0:
        return "一部出荷済み・未出荷分あり"
    if state_code == "SHIPPED":
        return "出荷完了"
    if int(row.get("hold_flag") or 0) == 1:
        return "保留中"
    return "-"


def _operation_hint(row, operation):
    state_label = get_state_label(row.get("state_code"))
    qty_unshipped = float(row.get("qty_unshipped") or 0)
    if row.get("state_code") in OPERATION_HIDDEN_STATES:
        return f"{state_label}のため対象外"
    if qty_unshipped <= 0:
        return "未出荷数量がないため対象外"

    if operation == "ship_confirm":
        if int(row.get("hold_flag") or 0) == 1:
            return "保留中のため出荷確定不可"
        if row.get("approval_status") not in {"NOT_REQUIRED", "APPROVED"}:
            return f"承認状態が{get_approval_label(row.get('approval_status'))}のため不可"
        if row.get("state_code") not in SHIP_CONFIRM_ALLOWED_STATES:
            return f"{state_label}は出荷確定対象外"
        return "未出荷分があり出荷確定できます"

    if row.get("state_code") not in RELEASE_ALLOWED_STATES:
        return f"{state_label}は引当解除対象外"
    return "未出荷分の引当を解除できます"


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


def _find_return_focus_row(rows):
    focus_line_id = st.session_state.get("return_focus_line_id")
    if focus_line_id is None:
        return None
    try:
        focus_line_id = int(focus_line_id)
    except (TypeError, ValueError):
        return None
    return next((row for row in rows if int(row.get("line_id") or 0) == focus_line_id), None)


def _select_label(row):
    return f"指示ID {row['order_id']} / 明細ID {row['line_id']} / 商品 {row['item_code']}"


def _valid_filter_values(values, options):
    option_set = set(options)
    return [value for value in values or [] if value in option_set]


def _saved_filters():
    filters = st.session_state.get(FILTER_STATE_KEY)
    return filters if isinstance(filters, dict) else {}


def _save_filters(
    selected_states,
    selected_approval_statuses,
    hold_only,
    item_code_filter,
    order_id_filter,
    user_filter,
):
    st.session_state[FILTER_STATE_KEY] = {
        "state_codes": list(selected_states),
        "approval_status": list(selected_approval_statuses),
        "hold_only": bool(hold_only),
        "item_code": item_code_filter,
        "order_id": order_id_filter,
        "updated_by": user_filter,
    }


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


def _route_message(row):
    state_code = row.get("state_code")
    if state_code == "PARTIAL_SHIPPED":
        return "一部出荷済みです。未出荷分が残っている場合は、出荷確定画面で続きを確認してください。"
    if state_code == "ALLOCATED":
        return "引当済みです。出荷確定へ進めます。"
    if state_code == "PARTIAL_ALLOCATED":
        return "一部引当です。不足や保留理由を確認し、必要に応じて監査ログまたは引当解除を確認してください。"
    if state_code == "HOLD":
        return "保留中です。まず監査ログで理由と履歴を確認してください。"
    if state_code == "REALLOC_PENDING":
        return "再引当待ちです。引当解除や再配分の履歴を確認してください。"
    if state_code == "SHIPPED":
        return "出荷完了済みです。操作ではなく履歴確認が中心です。"
    if state_code == "RELEASED":
        return "引当解除済みです。必要に応じて解除履歴を確認してください。"
    if state_code == "UNALLOCATED":
        return "未引当です。出荷確定や引当解除の対象外です。"
    if state_code in {"SENT_BACK", "CANCELLED"}:
        return "差戻しまたはキャンセル状態です。操作前に履歴を確認してください。"
    return "状態と履歴を確認し、必要に応じて次の操作へ進んでください。"


def _route_priority(row):
    state_code = row.get("state_code")
    if state_code == "PARTIAL_SHIPPED":
        return ["ship_confirm", "audit_log"]
    if state_code == "ALLOCATED":
        return ["ship_confirm", "audit_log"]
    if state_code == "PARTIAL_ALLOCATED":
        return ["audit_log", "release"]
    if state_code == "HOLD":
        return ["audit_log", "release"]
    if state_code == "REALLOC_PENDING":
        return ["release", "audit_log"]
    if state_code in {"SHIPPED", "RELEASED", "UNALLOCATED", "SENT_BACK", "CANCELLED"}:
        return ["audit_log"]
    return ["audit_log", "ship_confirm", "release"]


def _available_routes(row):
    routes = ["audit_log"]
    if _can_show_ship_confirm(row):
        routes.append("ship_confirm")
    if _can_show_release(row):
        routes.append("release")
    return routes


def _ordered_routes(row):
    preferred = _route_priority(row)
    available = _available_routes(row)
    ordered = [route for route in preferred if route in available]
    ordered.extend(route for route in available if route not in ordered)
    return ordered


def _visible_routes(row):
    return _ordered_routes(row)[:2]


def _route_caption(row, route):
    if route == "audit_log":
        return "選択明細の監査ログを確認できます"
    return _operation_hint(row, route)


def _render_route_button(row, route, primary=False):
    button_kwargs = {"key": f"state_list_route_{route}_{int(row['line_id'])}"}
    if primary:
        button_kwargs["type"] = "primary"
    if st.button(ROUTE_BUTTON_LABELS[route], **button_kwargs):
        st.session_state["detail_target"] = _build_detail_target(route, row)
        st.switch_page(DETAIL_PAGE_PATHS[route])
    st.caption(_route_caption(row, route))


st.title("📋 状態一覧")
st.write("今どの案件がどう止まっているかを、出荷明細単位で横断確認します。")
st.caption("数量の事実と業務状態を分けたまま、最新状態だけを一覧表示します。")

rows = get_all_line_state_rows()
state_options = sorted({row["state_code"] for row in rows if row.get("state_code")})
approval_options = sorted({row["approval_status"] for row in rows if row.get("approval_status")})
saved_filters = _saved_filters()

with st.expander("絞り込み条件", expanded=True):
    selected_states = st.multiselect(
        "状態",
        options=state_options,
        format_func=get_state_label,
        default=_valid_filter_values(saved_filters.get("state_codes"), state_options),
        key="state_list_filter_state_codes",
        placeholder="未選択で全状態",
    )
    selected_approval_statuses = st.multiselect(
        "承認状態",
        options=approval_options,
        format_func=get_approval_label,
        default=_valid_filter_values(saved_filters.get("approval_status"), approval_options),
        key="state_list_filter_approval_status",
        placeholder="未選択で全承認状態",
    )
    hold_only = st.checkbox(
        "保留のみ表示",
        value=bool(saved_filters.get("hold_only", False)),
        key="state_list_filter_hold_only",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        item_code_filter = st.text_input(
            "商品コード",
            value=str(saved_filters.get("item_code") or ""),
            key="state_list_filter_item_code",
            placeholder="例: ITEM-001",
        )
    with c2:
        order_id_filter = st.text_input(
            "指示ID",
            value=str(saved_filters.get("order_id") or ""),
            key="state_list_filter_order_id",
            placeholder="例: 1001",
        )
    with c3:
        user_filter = st.text_input(
            "更新者",
            value=str(saved_filters.get("updated_by") or ""),
            key="state_list_filter_updated_by",
            placeholder="例: zen",
        )
    if st.button("絞り込みをリセット"):
        st.session_state.pop(FILTER_STATE_KEY, None)
        for key in [
            "state_list_filter_state_codes",
            "state_list_filter_approval_status",
            "state_list_filter_hold_only",
            "state_list_filter_item_code",
            "state_list_filter_order_id",
            "state_list_filter_updated_by",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

_save_filters(
    selected_states,
    selected_approval_statuses,
    hold_only,
    item_code_filter,
    order_id_filter,
    user_filter,
)

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
            "状態メモ": _state_note(row),
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
    "状態メモ",
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
        column_config={
            "必要数": st.column_config.NumberColumn(format="%.2f"),
            "引当済数量": st.column_config.NumberColumn(format="%.2f"),
            "出荷済数量": st.column_config.NumberColumn(format="%.2f"),
            "未出荷数量": st.column_config.NumberColumn(format="%.2f"),
            "状態理由": st.column_config.TextColumn(width="small"),
            "状態メモ": st.column_config.TextColumn(width="medium"),
            "承認状態": st.column_config.TextColumn(width="small"),
        },
        on_select="rerun",
        selection_mode="single-row",
    )
except TypeError:
    st.dataframe(df[display_cols], width="stretch")

selected_row = _get_selected_row(selection_event, filtered_rows)

if selected_row is None:
    focus_row = _find_return_focus_row(filtered_rows)
    auto_row = focus_row or (filtered_rows[0] if len(filtered_rows) == 1 else None)
    select_options = {_select_label(row): row for row in filtered_rows}
    auto_label = _select_label(auto_row) if auto_row is not None else ""
    select_labels = list(select_options.keys())
    select_choices = [""] + select_labels
    auto_index = select_choices.index(auto_label) if auto_label else 0
    line_id_text = ",".join(str(row.get("line_id")) for row in filtered_rows)
    line_id_signature = hashlib.sha1(line_id_text.encode("utf-8")).hexdigest()[:12]
    auto_line_id = auto_row.get("line_id") if auto_row is not None else "none"
    select_key = f"state_list_detail_select_{auto_line_id}_{line_id_signature}"
    if focus_row is not None:
        st.info(
            st.session_state.get("return_focus_message")
            or "直前操作した明細があります。詳細確認対象に選択しています。"
        )
    elif st.session_state.get("return_focus_line_id") is not None:
        st.info("直前操作した明細がありますが、現在の絞り込み結果には含まれていません。")
        if len(filtered_rows) > 1:
            st.caption("詳細確認対象を選ぶと、状態履歴と操作導線が表示されます。")
    elif len(filtered_rows) == 1:
        st.info("現在の候補は1件だけです。詳細確認対象として選択しています。")
    else:
        st.caption("詳細確認対象を選ぶと、状態履歴と操作導線が表示されます。")

    selected_label = st.selectbox(
        "詳細確認対象",
        options=select_choices,
        index=auto_index,
        key=select_key,
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
            "状態が無いという意味ではなく、必要数・引当済数量・出荷済数量などの"
            "数量事実から現在状態を推定して表示している可能性があります。"
        )
    else:
        history_display_rows = []
        for history_row in history_rows:
            history_display_rows.append(
                {
                    "更新日時": _format_event_at(history_row["changed_at"]),
                    "状態": get_state_label(history_row["state_code"]),
                    "状態理由": get_reason_label(history_row["state_reason"]),
                    "自由記述": _display_text(history_row["free_note"]),
                    "保留": "はい" if int(history_row["hold_flag"] or 0) == 1 else "-",
                    "保留理由": _display_text(history_row["hold_reason"]),
                    "承認要否": _approval_required_label(history_row["approval_required"]),
                    "承認状態": get_approval_label(history_row["approval_status"]),
                    "影響案件数": int(history_row["impact_order_count"] or 0),
                    "更新者": _display_text(history_row["changed_by"]),
                }
            )
        history_df = pd.DataFrame(history_display_rows)
        st.caption("新しい履歴から順に表示しています。長い理由や自由記述は列内で確認できます。")
        st.dataframe(
            history_df[
                [
                    "更新日時",
                    "状態",
                    "状態理由",
                    "自由記述",
                    "保留",
                    "保留理由",
                    "承認要否",
                    "承認状態",
                    "影響案件数",
                    "更新者",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "更新日時": st.column_config.TextColumn(width="medium"),
                "状態": st.column_config.TextColumn(width="small"),
                "状態理由": st.column_config.TextColumn(width="medium"),
                "自由記述": st.column_config.TextColumn(width="large"),
                "保留理由": st.column_config.TextColumn(width="medium"),
                "承認要否": st.column_config.TextColumn(width="small"),
                "承認状態": st.column_config.TextColumn(width="small"),
                "影響案件数": st.column_config.NumberColumn(width="small"),
                "更新者": st.column_config.TextColumn(width="small"),
            },
        )
    st.info(_route_message(selected_row))
    visible_routes = _visible_routes(selected_row)
    action_cols = st.columns(max(len(visible_routes), 1))
    for idx, route in enumerate(visible_routes):
        with action_cols[idx]:
            _render_route_button(selected_row, route, primary=(idx == 0))
