import streamlit as st
from datetime import datetime
from core.db import init_db, insert_transaction, get_recent_transactions, log_audit_event

init_db()

st.title("📥 入庫処理")

st.write("商品を倉庫へ入れる時の記録を残します。")

with st.form("receipt_form"):
    col1, col2 = st.columns(2)

    with col1:
        item_code = st.text_input("商品コード", placeholder="ITEM-001")
        location_code = st.text_input("ロケーション", placeholder="A-01-01")
        qty = st.number_input("数量", min_value=0.0, step=1.0)

    with col2:
        lot_no = st.text_input("ロットNo", placeholder="LOT-20260412")
        operator = st.text_input("作業者", placeholder="zen")
        reason = st.text_input("理由", value="通常入庫")

    submitted = st.form_submit_button("入庫を記録")

    if submitted:
        item_code = item_code.strip()
        location_code = location_code.strip()
        lot_no = lot_no.strip()
        operator = operator.strip()
        reason = reason.strip()

        if not item_code:
            st.error("商品コードを入力してください")
        elif not location_code:
            st.error("ロケーションを入力してください")
        elif qty <= 0:
            st.error("数量は0より大きくしてください")
        else:
            tx_time = datetime.now().isoformat(timespec="seconds")
            insert_transaction(
                tx_type="receipt",
                item_code=item_code,
                location_code=location_code,
                qty=qty,
                lot_no=lot_no or None,
                reason=reason or None,
                operator=operator or None,
                tx_time=tx_time,
            )
            log_audit_event(
                event_type="RECEIPT",
                user_id=operator or None,
                item_code=item_code,
                location_code=location_code,
                after_value={
                    "qty": float(qty),
                    "lot_no": lot_no or None,
                    "reason": reason or None,
                    "tx_time": tx_time,
                },
                free_note="入庫処理",
            )
            st.success("入庫を記録しました")
            st.rerun()

st.divider()

st.subheader("最近の在庫イベント")

rows = get_recent_transactions(limit=20)

if rows:
    table_data = [dict(row) for row in rows]
    st.dataframe(table_data, width="stretch")
else:
    st.info("まだ在庫イベントはありません")
