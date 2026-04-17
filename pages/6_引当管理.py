import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    create_order_with_lines,
    get_recent_order_lines,
    get_physical_stock_by_item,
    get_allocation_strategy,
    get_enhanced_order_lines,
    get_approval_label,
    get_reason_options,
    get_state_label,
    save_line_state,
    log_audit_event,
)

init_db()

st.title("📌 引当管理（P0最小共通基盤版）")
st.write("出荷指示を登録し、引当結果に状態・理由・承認要否・影響件数を載せます。")
st.caption(f"現在の引当戦略: {get_allocation_strategy()}")

with st.expander("現在庫サマリ（商品コード合計）", expanded=False):
    phys = get_physical_stock_by_item()
    if phys:
        summary = [{"商品コード": k, "現物在庫計": v} for k, v in sorted(phys.items())]
        st.dataframe(pd.DataFrame(summary), width="stretch")
    else:
        st.info("在庫トランザクションから集計できる現物在庫はまだありません")


def parse_detail_lines(text: str):
    result = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            return None, f"カンマ区切りで入力してください: {raw}"
        left, right = line.split(",", 1)
        item = left.strip()
        if not item:
            return None, f"商品コードが空です: {raw}"
        try:
            qty = float(right.strip())
        except ValueError:
            return None, f"数量が数値ではありません: {raw}"
        if qty <= 0:
            return None, f"数量は0より大きくしてください: {raw}"
        result.append((item, qty))
    if not result:
        return None, "有効な明細行がありません（例: ITEM-001,10）"
    return result, None


with st.form("alloc_order_form"):
    reference = st.text_input("出荷指示番号（参照用）", placeholder="SO-20260412-001")
    note = st.text_input("備考", placeholder="")
    detail_text = st.text_area(
        "明細（1行につき1品目。形式: 商品コード,数量）",
        height=160,
        placeholder="ITEM-001,10\nITEM-002,5",
    )
    operator = st.text_input("作業者", value="zen")
    submitted = st.form_submit_button("出荷指示を登録（引当計算）")

    if submitted:
        ref = reference.strip()
        if not ref:
            st.error("出荷指示番号を入力してください")
        else:
            lines, err = parse_detail_lines(detail_text)
            if err:
                st.error(err)
            else:
                order_id, results = create_order_with_lines(ref, note.strip() or None, lines)
                if order_id is None:
                    st.error("明細の登録に失敗しました")
                else:
                    for row in get_enhanced_order_lines(order_id):
                        state_code = row["state_code"]
                        ok, msg = save_line_state(
                            line_id=row["line_id"],
                            state_code=state_code,
                            state_reason=None,
                            hold_flag=False,
                            approval_required=False,
                            approval_status="NOT_REQUIRED",
                            impact_order_count=row["impact_order_count"],
                            changed_by=operator.strip() or None,
                            free_note="新規引当登録",
                        )
                    log_audit_event(
                        event_type="ALLOCATE",
                        user_id=operator.strip() or None,
                        order_id=order_id,
                        order_no=ref,
                        after_value=results,
                        free_note="出荷指示登録と引当計算",
                    )
                    st.success(f"出荷指示を登録しました（order_id={order_id}）")
                    st.session_state["last_alloc_order_id"] = order_id
                    st.rerun()

last_order_id = st.session_state.get("last_alloc_order_id")
if last_order_id:
    st.divider()
    st.subheader(f"直近登録 order_id={last_order_id} の引当状態")
    latest_rows = get_enhanced_order_lines(last_order_id)
    if latest_rows:
        reason_labels = get_reason_options()
        df_latest = pd.DataFrame(latest_rows)
        if "state_reason" in df_latest.columns:
            df_latest["state_reason"] = df_latest["state_reason"].map(
                lambda code: reason_labels.get(code, code) if code else "-"
            )
        if "state_code" in df_latest.columns:
            df_latest["state_code"] = df_latest["state_code"].map(get_state_label)
        if "approval_status" in df_latest.columns:
            df_latest["approval_status"] = df_latest["approval_status"].map(get_approval_label)
        df_latest = df_latest.rename(
            columns={
                "line_id": "明細ID",
                "item_code": "商品コード",
                "qty_required": "必要数",
                "qty_allocated": "引当済数量",
                "qty_unshipped": "未出荷数量",
                "state_code": "状態コード",
                "state_label": "状態",
                "state_reason": "状態理由",
                "impact_order_count": "影響案件数",
                "approval_required": "承認要否",
                "approval_status": "承認コード",
                "approval_label": "承認状態",
                "changed_by": "更新者",
                "changed_at": "更新日時",
            }
        )
        show_cols = [
            "明細ID", "商品コード", "必要数", "引当済数量", "未出荷数量",
            "状態", "状態理由", "影響案件数", "承認要否", "承認状態",
            "更新者", "更新日時"
        ]
        st.dataframe(df_latest[show_cols], width="stretch")

        st.caption("必要に応じて状態だけ手動更新")
        reason_options = [""] + list(get_reason_options().keys())
        state_options = ["UNALLOCATED", "PARTIAL_ALLOCATED", "ALLOCATED", "REALLOC_PENDING", "HOLD"]
        approval_options = ["NOT_REQUIRED", "WAITING", "APPROVED", "REJECTED"]
        for row in latest_rows:
            lid = int(row["line_id"])
            with st.expander(f"明細 {lid} / {row['item_code']} の状態更新", expanded=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    state_code = st.selectbox(
                        "状態",
                        options=state_options,
                        index=state_options.index(row["state_code"] if row["state_code"] in state_options else "ALLOCATED"),
                        format_func=get_state_label,
                        key=f"alloc_state_{lid}",
                    )
                with c2:
                    reason_code = st.selectbox(
                        "理由コード",
                        options=reason_options,
                        format_func=lambda code: reason_labels.get(code, "選択してください") if code else "選択してください",
                        key=f"alloc_reason_{lid}",
                    )
                with c3:
                    approval_required = st.checkbox("承認要否", value=bool(row["approval_required"]), key=f"alloc_appr_req_{lid}")
                approval_status = st.selectbox(
                    "承認状態",
                    options=approval_options,
                    index=approval_options.index(row["approval_status"] if row["approval_status"] in approval_options else "NOT_REQUIRED"),
                    format_func=get_approval_label,
                    key=f"alloc_appr_status_{lid}",
                )
                hold_flag = st.checkbox("保留", value=bool(row["hold_flag"]), key=f"alloc_hold_{lid}")
                hold_reason = st.text_input("保留理由", value=row.get("hold_reason") or "", key=f"alloc_hold_reason_{lid}")
                if st.button("状態を保存", key=f"save_alloc_state_{lid}"):
                    if row["impact_order_count"] > 0 and state_code == "REALLOC_PENDING" and not reason_code:
                        st.error("他案件影響ありの再引当待ちは理由コードが必要です")
                    elif approval_required and approval_status != "APPROVED":
                        st.warning("承認要のままです。承認待ちでも保存はできますが、出荷確定では停止します")
                        ok, msg = save_line_state(
                            line_id=lid,
                            state_code=state_code,
                            state_reason=reason_code or None,
                            hold_flag=hold_flag,
                            hold_reason=hold_reason or None,
                            approval_required=approval_required,
                            approval_status=approval_status,
                            impact_order_count=row["impact_order_count"],
                            changed_by=operator.strip() or None,
                            free_note="引当管理画面から更新",
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                    else:
                        ok, msg = save_line_state(
                            line_id=lid,
                            state_code=state_code,
                            state_reason=reason_code or None,
                            hold_flag=hold_flag,
                            hold_reason=hold_reason or None,
                            approval_required=approval_required,
                            approval_status=approval_status,
                            impact_order_count=row["impact_order_count"],
                            changed_by=operator.strip() or None,
                            free_note="引当管理画面から更新",
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()

st.divider()
st.subheader("最近の引当明細")
rows = get_recent_order_lines(limit=40)
if rows:
    df_hist = pd.DataFrame([dict(row) for row in rows])
    df_hist = df_hist.rename(
        columns={
            "order_id": "指示ID",
            "reference": "出荷指示番号",
            "order_created": "登録日時",
            "line_id": "明細ID",
            "item_code": "商品コード",
            "qty_required": "必要数",
            "qty_allocated": "引当済数量",
            "qty_pending": "未引当",
        }
    )
    st.dataframe(df_hist, width="stretch")
else:
    st.info("まだ引当明細はありません")
