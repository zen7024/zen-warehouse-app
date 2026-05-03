from typing import Optional, Tuple

import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    list_orders_with_releasable_allocations,
    get_enhanced_order_lines,
    release_allocation_for_line,
    get_approval_label,
    get_release_blockers,
    get_recent_release_logs,
    get_reason_label,
    get_state_label,
    save_line_state,
    get_order_competition_by_item,
    build_alloc_status,
    STATE,
    update_line_state,
)

init_db()
DETAIL_TARGET_PAGE = "release"
STATE_LIST_PAGE_PATH = "pages/11_状態一覧.py"

RELEASE_REASON_CODES = [
    "CUSTOMER_CHANGE",
    "PRIORITY_REALLOC",
    "WRONG_ALLOC",
    "STOCK_DIFF",
    "OTHER",
]


def _set_return_focus(order_id, line_id, item_code=None, message=None):
    st.session_state["return_focus_order_id"] = int(order_id)
    st.session_state["return_focus_line_id"] = int(line_id)
    st.session_state["return_focus_message"] = message or (
        f"直前に操作した 指示ID {order_id} / 明細ID {line_id} を表示しています。状態と履歴を確認してください。"
    )
    if item_code:
        st.session_state["return_focus_item_code"] = item_code


def _show_state_list_return_button(key):
    if st.button("状態一覧で再確認", key=key):
        st.switch_page(STATE_LIST_PAGE_PATH)


def _build_release_success_message(order_id, line_id, item_code=None, released_qty=None):
    item_part = f" / 商品コード {item_code}" if item_code else ""
    qty_part = f" / 解除数量 {released_qty:g}" if released_qty is not None else ""
    return (
        f"引当解除しました。直前に解除した対象は 指示ID {order_id} / 明細ID {line_id}"
        f"{item_part}{qty_part} です。"
        "この対象は解除可能一覧から外れる場合があります。"
        "状態一覧または監査ログで履歴を確認してください。"
    )


def _apply_detail_target(orders):
    target = st.session_state.get("detail_target")
    if not target or target.get("target_page") != DETAIL_TARGET_PAGE:
        return None

    target_order_id = target.get("order_id")
    target_line_id = target.get("line_id")
    order_ids = {int(r["order_id"]) for r in orders}

    st.session_state.pop("detail_target", None)
    if target_order_id not in order_ids:
        st.session_state["release_nav_warning"] = (
            f"状態一覧から受け取った 指示ID {target_order_id} は、引当解除対象として見つかりませんでした。"
        )
        return None

    st.session_state["release_target"] = {
        "source_page": target.get("source_page"),
        "target_page": target.get("target_page"),
        "order_id": int(target_order_id),
        "line_id": int(target_line_id) if target_line_id is not None else None,
        "item_code": target.get("item_code"),
        "state_code": target.get("state_code"),
    }
    st.session_state["release_nav_message"] = (
        f"状態一覧から 指示ID {target_order_id} / 明細ID {target_line_id} を引き継いで表示しています。"
    )
    return st.session_state["release_target"]


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


def _next_state_after_release_from_line(line: dict) -> str:
    """解除後の数量から order_state_logs 用の state_code を決める（出荷実績優先）。"""
    req = float(line.get("qty_required") or 0)
    alloc = float(line.get("qty_allocated") or 0)
    ship = float(line.get("shipped_qty") or 0)

    if ship >= req and req > 0:
        return "SHIPPED"
    if ship > 0:
        return "PARTIAL_SHIPPED"
    if alloc <= 1e-9:
        return "RELEASED"
    if alloc < req - 1e-9:
        return "PARTIAL_ALLOCATED"
    return "ALLOCATED"


def _finalize_release_and_audit(
    *,
    line_id: int,
    order_id: int,
    snapshot_row: dict,
    item_code: str,
    released_qty: float,
    reason_code: Optional[str],
    approval_required: bool,
    approval_status: str,
    operator: Optional[str],
    free_note_state: str,
) -> Tuple[bool, Optional[str]]:
    """
    解除成功後: 最新明細で状態を判定し save_line_state を行う。
    戻り値: (成功, エラーメッセージ or None)
    """
    refreshed = get_enhanced_order_lines(order_id)
    updated = next((r for r in refreshed if int(r["line_id"]) == line_id), None)
    if not updated:
        return False, "解除後の明細を再取得できませんでした"

    next_state = _next_state_after_release_from_line(updated)
    impact = int(updated.get("impact_order_count") or snapshot_row.get("impact_order_count") or 0)

    save_line_state(
        line_id=line_id,
        state_code=next_state,
        state_reason=reason_code or None,
        hold_flag=False,
        hold_reason=None,
        approval_required=approval_required,
        approval_status=approval_status,
        impact_order_count=impact,
        changed_by=operator.strip() or None,
        free_note=free_note_state,
    )
    return True, None


st.title("🔓 引当解除（P0最小共通基盤版）")
st.write("未出荷引当だけを解除し、理由・承認・影響表示を載せます。")

if st.session_state.get("release_success_message"):
    st.success(st.session_state.get("release_success_message"))
    _show_state_list_return_button("release_back_to_state_list")

orders = list_orders_with_releasable_allocations()
if not orders:
    st.info("解除可能な未出荷引当を含む出荷指示はありません。")
    st.stop()

target = _apply_detail_target(orders) or st.session_state.get("release_target")

labels = []
label_to_order_id = {}
for r in orders:
    ref = (r["reference"] or "").strip() or "(番号なし)"
    label = f"{ref} ・ 指示ID {r['order_id']}"
    labels.append(label)
    label_to_order_id[label] = r["order_id"]

default_index = 0
if target:
    target_order_id = int(target["order_id"])
    for idx, label in enumerate(labels):
        if label_to_order_id[label] == target_order_id:
            default_index = idx
            break

chosen_label = st.selectbox("出荷指示", labels, index=default_index)
order_id = label_to_order_id[chosen_label]
rows = get_enhanced_order_lines(order_id)
target_line_id = int(target["line_id"]) if target and target.get("order_id") == order_id and target.get("line_id") is not None else None

if st.session_state.get("release_nav_warning"):
    st.info(st.session_state.get("release_nav_warning"))
    st.session_state.pop("release_nav_warning", None)

if st.session_state.get("release_nav_message") and target_line_id is not None:
    st.info(st.session_state.get("release_nav_message"))
    st.session_state.pop("release_nav_message", None)

if not rows:
    st.warning("この指示に明細がありません")
    st.stop()

target_row = None
if target_line_id is not None:
    target_row = next((row for row in rows if int(row["line_id"]) == target_line_id), None)
    if target_row is None:
        st.info("状態一覧から引き継いだ明細は、この出荷指示内では見つかりませんでした。")
    elif float(target_row.get("qty_unshipped") or 0) <= 0:
        st.info("状態一覧から引き継いだ明細は、現在は解除可能な未出荷引当がありません。")
    else:
        st.caption(
            f"引き継ぎ対象: 明細ID {target_line_id} / 商品コード {target_row['item_code']} / "
            f"未出荷引当 {float(target_row['qty_unshipped'] or 0):g}"
        )

action_rows = [target_row] if target_row is not None else rows

df = pd.DataFrame(rows)
if "state_reason" in df.columns:
    df["state_reason"] = df["state_reason"].map(get_reason_label)
if "state_code" in df.columns:
    df["state_code"] = df["state_code"].map(get_state_label)
if "approval_status" in df.columns:
    df["approval_status"] = df["approval_status"].map(get_approval_label)
df["業務状態"] = df.apply(
    lambda r: STATE.get(update_line_state(
        float(r.get("qty_required") or 0),
        float(r.get("qty_allocated") or 0),
        float(r.get("shipped_qty") or 0),
        int(r.get("hold_flag") or 0),
    ), "-"),
    axis=1,
)
df = df.rename(
    columns={
        "line_id": "明細ID",
        "item_code": "商品コード",
        "qty_required": "必要数",
        "qty_allocated": "引当済数量",
        "shipped_qty": "出荷済数量",
        "qty_unshipped": "未出荷数量",
        "state_code": "状態コード",
        "state_label": "状態",
        "state_reason": "状態理由",
        "approval_required": "承認要否",
        "approval_status": "承認コード",
        "approval_label": "承認状態",
        "impact_order_count": "解除後影響案件数",
        "changed_by": "更新者",
    }
)
show_cols = [
    "明細ID", "商品コード", "必要数", "引当済数量", "出荷済数量",
    "未出荷数量", "業務状態", "状態", "状態理由", "承認要否", "承認状態", "解除後影響案件数", "更新者"
]
st.dataframe(df[show_cols], use_container_width=True)

st.divider()
st.subheader("解除操作")
reason_options = [""] + RELEASE_REASON_CODES
approval_options = ["NOT_REQUIRED", "WAITING", "APPROVED", "REJECTED"]
operator = st.text_input("作業者（任意）", value="zen")

any_releasable = False
for row in action_rows:
    lid = int(row["line_id"])
    item = row["item_code"]
    releasable = float(row["qty_unshipped"])
    if releasable <= 1e-9:
        continue
    any_releasable = True

    st.markdown(f"**明細 ID {lid}** ・ {item}")
    release_memo = st.text_input(
        "自由記述（任意。理由コードがその他の場合は必須）",
        value="",
        placeholder="例: 優先変更のため一時解放、他案件への振り向け など",
        key=f"release_memo_{lid}",
    )
    with st.expander("同一商品の案件競合一覧", expanded=False):
        st.caption("同一商品の他出荷指示との取り合いを確認できます。")
        comp = get_order_competition_by_item(item)
        disp = _competition_display_rows(comp)
        if not disp:
            st.info("この商品コードの出荷明細はまだありません。")
        else:
            st.dataframe(pd.DataFrame(disp), use_container_width=True)
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.0, 1.0])
    with c1:
        qty_in = st.number_input(
            "解除する数量",
            min_value=0.0,
            max_value=releasable,
            value=0.0,
            step=1.0,
            key=f"release_qty_{lid}",
        )
    with c2:
        reason_code = st.selectbox(
            "解除理由コード（必須）",
            options=reason_options,
            format_func=lambda code: get_reason_label(code, "選択してください") if code else "選択してください",
            key=f"release_reason_{lid}",
        )
    with c3:
        approval_required = st.checkbox("承認要否", value=bool(row["approval_required"]), key=f"release_appr_req_{lid}")
        approval_status = st.selectbox(
            "承認状態",
            options=approval_options,
            index=approval_options.index(row["approval_status"] if row["approval_status"] in approval_options else "NOT_REQUIRED"),
            format_func=get_approval_label,
            key=f"release_appr_status_{lid}",
        )
    with c4:
        if st.button("指定数量を解除", key=f"release_btn_{lid}"):
            blockers = get_release_blockers(
                line_id=lid,
                reason_code=reason_code or None,
                approval_required=approval_required,
                approval_status=approval_status,
                free_note=release_memo,
            )
            if blockers:
                for msg in blockers:
                    st.error(msg)
            else:
                ok, msg = release_allocation_for_line(
                    lid,
                    qty_in,
                    reason_code=reason_code,
                    free_note=release_memo,
                    operator=operator,
                )
                if ok:
                    fin_ok, fin_err = _finalize_release_and_audit(
                        line_id=lid,
                        order_id=order_id,
                        snapshot_row=row,
                        item_code=item,
                        released_qty=qty_in,
                        reason_code=reason_code or None,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        operator=operator,
                        free_note_state="引当解除（指定数量）",
                    )
                    if not fin_ok:
                        st.error(fin_err or "解除後処理に失敗しました")
                    else:
                        _set_return_focus(
                            order_id,
                            lid,
                            item,
                            f"引当解除した 指示ID {order_id} / 明細ID {lid} を表示しています。状態と履歴を確認してください。",
                        )
                        st.session_state["release_success_message"] = _build_release_success_message(
                            order_id,
                            lid,
                            item,
                            qty_in,
                        )
                        st.rerun()
                else:
                    st.error(msg)
        if st.button("全解除", key=f"release_all_{lid}"):
            blockers = get_release_blockers(
                line_id=lid,
                reason_code=reason_code or None,
                approval_required=approval_required,
                approval_status=approval_status,
                free_note=release_memo,
            )
            if blockers:
                for msg in blockers:
                    st.error(msg)
            else:
                ok, msg = release_allocation_for_line(
                    lid,
                    releasable,
                    reason_code=reason_code,
                    free_note=release_memo,
                    operator=operator,
                )
                if ok:
                    fin_ok, fin_err = _finalize_release_and_audit(
                        line_id=lid,
                        order_id=order_id,
                        snapshot_row=row,
                        item_code=item,
                        released_qty=releasable,
                        reason_code=reason_code or None,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        operator=operator,
                        free_note_state="引当解除（全解除）",
                    )
                    if not fin_ok:
                        st.error(fin_err or "解除後処理に失敗しました")
                    else:
                        _set_return_focus(
                            order_id,
                            lid,
                            item,
                            f"引当解除した 指示ID {order_id} / 明細ID {lid} を表示しています。状態と履歴を確認してください。",
                        )
                        st.session_state["release_success_message"] = _build_release_success_message(
                            order_id,
                            lid,
                            item,
                            releasable,
                        )
                        st.rerun()
                else:
                    st.error(msg)

if not any_releasable:
    st.info("この指示には解除可能な未出荷引当がありません。")

st.divider()
st.subheader("最近の解除履歴")
release_logs = get_recent_release_logs(limit=10)
if release_logs:
    log_rows = []
    for r in release_logs:
        log_rows.append(
            {
                "解除日時": r["event_at"],
                "作業者": r["user_id"] or "-",
                "指示ID": r["order_id"],
                "明細ID": r["line_id"],
                "商品コード": r["item_code"],
                "解除理由": get_reason_label(r["reason_code"]),
                "自由記述": r["free_note"] or "",
            }
        )
    st.dataframe(pd.DataFrame(log_rows), use_container_width=True)
else:
    st.info("解除履歴はまだありません。")
