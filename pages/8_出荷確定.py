import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    list_orders_for_ship_confirm,
    get_enhanced_order_lines,
    get_allocation_details_for_order,
    confirm_shipment_for_order,
    get_approval_label,
    get_reason_options,
    get_shipment_blockers,
    get_shortage_candidates_for_order,
    get_state_label,
    save_line_state,
    log_audit_event,
)

init_db()

st.title("🚚 出荷確定（P0最小共通基盤版）")
st.write("未出荷数量・状態・承認要否を見ながら、異常時は止めて出荷確定します。")

orders = list_orders_for_ship_confirm()
if not orders:
    st.info("出荷指示がありません。先に引当管理で指示を登録してください。")
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

if st.session_state.get("a06_order_id") not in (None, order_id):
    for k in [
        "a06_order_id",
        "a06_line_ship_qty_map",
        "a06_reason_code",
        "a06_shortage_rows",
        "a06_blockers",
        "debug_a06",
    ]:
        st.session_state.pop(k, None)

if st.session_state.get("a06_success_message"):
    st.success(st.session_state.get("a06_success_message"))
    st.session_state.pop("a06_success_message", None)

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
        "hold_flag": "保留",
        "impact_order_count": "影響案件数",
    }
)
show_cols = [
    "明細ID", "商品コード", "必要数", "引当済数量", "出荷済数量", "未出荷数量",
    "状態", "状態理由", "承認要否", "承認状態", "保留", "影響案件数"
]
st.dataframe(df[show_cols], width="stretch")

ad_rows = get_allocation_details_for_order(order_id)
if ad_rows:
    with st.expander("ロケーション別引当・未出荷内訳", expanded=True):
        df_ad = pd.DataFrame([dict(row) for row in ad_rows])
        df_ad = df_ad.rename(
            columns={
                "line_id": "明細ID",
                "item_code": "商品コード",
                "location_code": "ロケーション",
                "allocated_qty": "引当済数量",
                "shipped_qty": "出荷済数量",
                "qty_unshipped": "未出荷数量",
            }
        )
        st.dataframe(df_ad, width="stretch")
else:
    st.info("この指示にはロケーション別引当明細がありません（旧形式）。")

has_unshipped = any(float(dict(row)["qty_unshipped"]) > 0 for row in rows)
if not has_unshipped:
    st.info("この指示は未出荷の引当がありません。")
    st.stop()

line_ship_qty_map = {}
st.subheader("今回出荷数量")
for row in rows:
    d = dict(row)
    line_id = int(d["line_id"])
    qty_unshipped = float(d["qty_unshipped"])
    if qty_unshipped <= 0:
        continue
    line_ship_qty_map[line_id] = st.number_input(
        f"明細 {line_id} / 商品 {d['item_code']}（未出荷 {qty_unshipped:g}）",
        min_value=0.0,
        max_value=qty_unshipped,
        value=qty_unshipped,
        step=1.0,
        key=f"ship_qty_{line_id}",
    )

reason_options = [""] + list(get_reason_options().keys())
default_reason_code = "NORMAL_SHIPMENT"
reason_code = st.selectbox(
    "出荷理由コード",
    options=reason_options,
    index=reason_options.index(default_reason_code) if default_reason_code in reason_options else 0,
    format_func=lambda code: reason_labels.get(code, "選択してください") if code else "選択してください",
)
operator = st.text_input("作業者", value="zen")
priority_override = st.checkbox("予定外ロケ/FIFO例外あり")
manual_hold = st.checkbox("この指示を保留にする")
hold_reason = st.text_input("保留理由", value="")

if manual_hold:
    for row in rows:
        if st.button(f"明細 {row['line_id']} を保留保存", key=f"hold_{row['line_id']}"):
            ok, msg = save_line_state(
                line_id=row["line_id"],
                state_code="HOLD",
                state_reason="MANUAL_HOLD",
                hold_flag=True,
                hold_reason=hold_reason or "手動保留",
                approval_required=False,
                approval_status="NOT_REQUIRED",
                impact_order_count=row["impact_order_count"],
                changed_by=operator.strip() or None,
                free_note="出荷確定画面から保留",
            )
            if ok:
                st.success(msg)
                st.rerun()

if st.button("出荷確定を実行", disabled=not has_unshipped, type="primary"):
    total_ship_qty = sum(float(v) for v in line_ship_qty_map.values())
    if total_ship_qty <= 0:
        st.error("今回出荷数量がすべて0です。1明細以上に数量を指定してください。")
        st.stop()

    blockers = get_shipment_blockers(order_id, line_ship_qty_map, reason_code=reason_code or None)
    if priority_override and not reason_code:
        blockers.append("予定外ロケ/FIFO例外ありの場合は理由コードが必要です")

    if blockers:
        st.error("出荷確定を中止しました")
        for msg in blockers:
            st.write(f"- {msg}")

        shortage_rows = get_shortage_candidates_for_order(order_id, line_ship_qty_map)
        st.session_state["a06_order_id"] = order_id
        st.session_state["a06_line_ship_qty_map"] = {int(k): float(v) for k, v in line_ship_qty_map.items()}
        st.session_state["a06_reason_code"] = reason_code or None
        st.session_state["a06_shortage_rows"] = shortage_rows
        st.session_state["a06_blockers"] = blockers
        st.session_state["debug_a06"] = []
        st.rerun()

    ok, msg, summary = confirm_shipment_for_order(
        order_id,
        line_ship_qty_map=line_ship_qty_map,
        operator=operator.strip() or None,
        reason=reason_code or "OTHER",
    )
    if ok:
        for row in rows:
            requested = float(line_ship_qty_map.get(int(row["line_id"]), 0.0) or 0.0)
            if requested <= 0:
                continue
            state_code = "SHIPPED"
            if requested < float(row["qty_unshipped"]):
                state_code = "PARTIAL_SHIPPED"
            save_line_state(
                line_id=row["line_id"],
                state_code=state_code,
                state_reason=reason_code or None,
                hold_flag=False,
                hold_reason=None,
                approval_required=False,
                approval_status="NOT_REQUIRED",
                impact_order_count=row["impact_order_count"],
                changed_by=operator.strip() or None,
                free_note="出荷確定後更新",
            )
        log_audit_event(
            event_type="SHIP_CONFIRM",
            user_id=operator.strip() or None,
            order_id=order_id,
            line_id=None,
            after_value=summary,
            reason_code=reason_code or None,
            free_note="出荷確定実行",
        )
        st.success(msg)
        st.rerun()
    else:
        st.error(msg)

a06_shortage_rows = st.session_state.get("a06_shortage_rows") or []
a06_order_id = st.session_state.get("a06_order_id")
if a06_order_id == order_id and a06_shortage_rows:
    st.divider()
    st.subheader("A-06対応: 保留へ切替")
    st.write("ロケ不足時は、まずHOLDへ切替えて出荷を止め、別ロケ確認後にREALLOC_PENDINGへ更新します。")
    st.caption("推奨操作: 1) まず HOLD  2) 次に別ロケ確認  3) その後 REALLOC_PENDING")

    for msg in st.session_state.get("a06_blockers") or []:
        st.write(f"- {msg}")

    df_shortage = pd.DataFrame(a06_shortage_rows).rename(
        columns={
            "line_id": "不足明細ID",
            "item_code": "商品コード",
            "location_code": "不足ロケ",
            "requested_qty": "必要数",
            "current_stock": "現在庫",
            "shortage_qty": "不足数",
        }
    )
    st.dataframe(
        df_shortage[["不足明細ID", "商品コード", "不足ロケ", "必要数", "現在庫", "不足数"]],
        width="stretch",
    )

    line_meta = {int(r["line_id"]): dict(r) for r in rows}
    shown_line_ids = []
    for idx, srow in enumerate(a06_shortage_rows):
        lid = int(srow["line_id"])
        if lid in shown_line_ids:
            continue
        shown_line_ids.append(lid)
        st.markdown(f"**明細 {lid} / 商品 {srow['item_code']} / 不足ロケ {srow['location_code']}**")
        hold_reason_a06 = st.text_input(
            "保留理由（A-06）",
            value=f"A-06 引当ロケ不足: loc={srow['location_code']}",
            key=f"a06_hold_reason_{lid}_{srow['location_code']}_{idx}",
        )
        if st.button(f"明細 {lid} をHOLD保存（SHORTAGE）", key=f"a06_hold_btn_{lid}_{srow['location_code']}_{idx}"):
            st.session_state["debug_a06"] = [
                "clicked",
                f"line_id={lid}",
            ]
            current = line_meta.get(lid, {})
            try:
                ok, msg = save_line_state(
                    line_id=lid,
                    state_code="HOLD",
                    state_reason="SHORTAGE",
                    hold_flag=True,
                    hold_reason=hold_reason_a06 or "A-06 引当ロケ不足",
                    approval_required=bool(current.get("approval_required")),
                    approval_status=current.get("approval_status") or "NOT_REQUIRED",
                    impact_order_count=int(current.get("impact_order_count") or 0),
                    changed_by=operator.strip() or None,
                    free_note="A-06対応: 出荷確定画面からHOLD",
                )
                st.session_state["debug_a06"].append(f"ok={ok}, msg={msg}")
                if ok:
                    log_audit_event(
                        event_type="A06_HOLD",
                        user_id=operator.strip() or None,
                        order_id=order_id,
                        line_id=lid,
                        item_code=srow["item_code"],
                        location_code=srow["location_code"],
                        reason_code="SHORTAGE",
                        after_value=srow,
                        free_note=hold_reason_a06 or None,
                    )
                    for k in [
                        "a06_order_id",
                        "a06_line_ship_qty_map",
                        "a06_reason_code",
                        "a06_shortage_rows",
                        "a06_blockers",
                        "debug_a06",
                    ]:
                        st.session_state.pop(k, None)
                    st.session_state["a06_success_message"] = "A-06対応でHOLD保存しました。引当管理でREALLOC_PENDINGへ進めてください。"
                    st.rerun()
                else:
                    st.error("HOLD保存に失敗しました。debug_a06を確認してください。")
            except Exception as e:
                st.session_state["debug_a06"].append(f"exception={repr(e)}")
                st.error("HOLD保存時に例外が発生しました。debug_a06を確認してください。")

    debug_a06 = st.session_state.get("debug_a06") or []
    if debug_a06:
        st.caption("debug_a06")
        for d in debug_a06:
            st.write(d)
