from typing import Optional, Tuple

import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    list_orders_with_releasable_allocations,
    get_enhanced_order_lines,
    release_allocation_for_line,
    get_approval_label,
    get_reason_options,
    get_release_blockers,
    get_state_label,
    save_line_state,
    log_audit_event,
)

init_db()


def _next_state_after_release_from_line(line: dict) -> str:
    """解除後の数量から order_state_logs 用の state_code を決める（未出荷引当ベース）。"""
    req = float(line.get("qty_required") or 0)
    alloc = float(line.get("qty_allocated") or 0)
    ship = float(line.get("shipped_qty") or 0)
    qty_unshipped = float(line.get("qty_unshipped", alloc - ship))
    if qty_unshipped <= 1e-9:
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
    free_note_audit: str,
) -> Tuple[bool, Optional[str]]:
    """
    解除成功後: 最新明細で状態を判定し save_line_state / RELEASE 監査を行う。
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
    log_audit_event(
        event_type="RELEASE",
        user_id=operator.strip() or None,
        order_id=order_id,
        line_id=line_id,
        item_code=item_code,
        before_value={
            "qty_allocated_before": float(snapshot_row["qty_allocated"]),
            "shipped_qty_before": float(snapshot_row["shipped_qty"]),
            "qty_unshipped_before": float(snapshot_row["qty_unshipped"]),
        },
        after_value={
            "released_qty": float(released_qty),
            "qty_allocated_after": float(updated["qty_allocated"]),
            "qty_unshipped_after": float(updated["qty_unshipped"]),
            "next_state": next_state,
        },
        reason_code=reason_code or None,
        free_note=free_note_audit,
    )
    return True, None


st.title("🔓 引当解除（P0最小共通基盤版）")
st.write("未出荷引当だけを解除し、理由・承認・影響表示を載せます。")

orders = list_orders_with_releasable_allocations()
if not orders:
    st.info("解除可能な未出荷引当を含む出荷指示はありません。")
    st.stop()

labels = []
label_to_order_id = {}
for r in orders:
    ref = (r["reference"] or "").strip() or "(番号なし)"
    label = f"{ref} ・ 指示ID {r['order_id']}"
    labels.append(label)
    label_to_order_id[label] = r["order_id"]

chosen_label = st.selectbox("出荷指示", labels)
order_id = label_to_order_id[chosen_label]
rows = get_enhanced_order_lines(order_id)

if not rows:
    st.warning("この指示に明細がありません")
    st.stop()

reason_labels = get_reason_options()
df = pd.DataFrame(rows)
if "state_reason" in df.columns:
    df["state_reason"] = df["state_reason"].map(
        lambda code: reason_labels.get(code, code) if code else "-"
    )
if "state_code" in df.columns:
    df["state_code"] = df["state_code"].map(get_state_label)
if "approval_status" in df.columns:
    df["approval_status"] = df["approval_status"].map(get_approval_label)
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
    "未出荷数量", "状態", "状態理由", "承認要否", "承認状態", "解除後影響案件数", "更新者"
]
st.dataframe(df[show_cols], width="stretch")

st.divider()
st.subheader("解除操作")
reason_options = [""] + list(get_reason_options().keys())
approval_options = ["NOT_REQUIRED", "WAITING", "APPROVED", "REJECTED"]
operator = st.text_input("操作者", value="zen")

any_releasable = False
for row in rows:
    lid = int(row["line_id"])
    item = row["item_code"]
    releasable = float(row["qty_unshipped"])
    if releasable <= 1e-9:
        continue
    any_releasable = True

    st.markdown(f"**明細 ID {lid}** ・ {item}")
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
            "理由コード",
            options=reason_options,
            format_func=lambda code: reason_labels.get(code, "選択してください") if code else "選択してください",
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
            )
            if blockers:
                for msg in blockers:
                    st.error(msg)
            else:
                ok, msg = release_allocation_for_line(lid, qty_in)
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
                        free_note_audit="指定数量解除",
                    )
                    if not fin_ok:
                        st.error(fin_err or "解除後処理に失敗しました")
                    else:
                        st.success(msg)
                        st.rerun()
                else:
                    st.error(msg)
        if st.button("全解除", key=f"release_all_{lid}"):
            blockers = get_release_blockers(
                line_id=lid,
                reason_code=reason_code or None,
                approval_required=approval_required,
                approval_status=approval_status,
            )
            if blockers:
                for msg in blockers:
                    st.error(msg)
            else:
                ok, msg = release_allocation_for_line(lid, releasable)
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
                        free_note_audit="全解除",
                    )
                    if not fin_ok:
                        st.error(fin_err or "解除後処理に失敗しました")
                    else:
                        st.success(msg)
                        st.rerun()
                else:
                    st.error(msg)

if not any_releasable:
    st.info("この指示には解除可能な未出荷引当がありません。")
