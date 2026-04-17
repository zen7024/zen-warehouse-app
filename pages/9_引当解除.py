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
                    save_line_state(
                        line_id=lid,
                        state_code="RELEASED",
                        state_reason=reason_code or None,
                        hold_flag=False,
                        hold_reason=None,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        impact_order_count=row["impact_order_count"],
                        changed_by=operator.strip() or None,
                        free_note="引当解除（指定数量）",
                    )
                    log_audit_event(
                        event_type="RELEASE",
                        user_id=operator.strip() or None,
                        order_id=order_id,
                        line_id=lid,
                        item_code=item,
                        before_value={"releasable": releasable},
                        after_value={"released_qty": qty_in},
                        reason_code=reason_code or None,
                        free_note="指定数量解除",
                    )
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
                    save_line_state(
                        line_id=lid,
                        state_code="RELEASED",
                        state_reason=reason_code or None,
                        hold_flag=False,
                        hold_reason=None,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        impact_order_count=row["impact_order_count"],
                        changed_by=operator.strip() or None,
                        free_note="引当解除（全解除）",
                    )
                    log_audit_event(
                        event_type="RELEASE",
                        user_id=operator.strip() or None,
                        order_id=order_id,
                        line_id=lid,
                        item_code=item,
                        before_value={"releasable": releasable},
                        after_value={"released_qty": releasable},
                        reason_code=reason_code or None,
                        free_note="全解除",
                    )
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

if not any_releasable:
    st.info("この指示には解除可能な未出荷引当がありません。")
