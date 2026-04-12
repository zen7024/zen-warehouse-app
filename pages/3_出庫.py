import streamlit as st
from datetime import datetime
from core.db import init_db, get_current_stock, insert_transaction, get_recent_transactions

init_db()

st.title("📤 出庫処理")
st.write("倉庫から商品を出す時の記録を残します。")


def _stock_at(rows, item_code: str, location_code: str) -> float:
    for row in rows:
        d = dict(row)
        if d["item_code"] == item_code and d["location_code"] == location_code:
            return float(d["stock_qty"])
    return 0.0


with st.form("issue_form"):
    col1, col2 = st.columns(2)

    with col1:
        item_code = st.text_input("商品コード", placeholder="ITEM-001")
        location_code = st.text_input("ロケーション", placeholder="A-01-01")
        qty = st.number_input("数量", min_value=0.0, step=1.0)

    with col2:
        operator = st.text_input("作業者", placeholder="zen")
        reason = st.text_input("理由", value="通常出庫")

    submitted = st.form_submit_button("出庫を記録")

    if submitted:
        item_code = item_code.strip()
        location_code = location_code.strip()
        operator = operator.strip()
        reason = reason.strip()

        if not item_code:
            st.error("商品コードを入力してください")
        elif not location_code:
            st.error("ロケーションを入力してください")
        elif qty <= 0:
            st.error("数量は0より大きくしてください")
        else:
            stock_rows = get_current_stock()
            available = _stock_at(stock_rows, item_code, location_code)

            if qty > available:
                st.error(f"在庫不足です。現在庫: {available}")
            else:
                insert_transaction(
                    tx_type="issue",
                    item_code=item_code,
                    location_code=location_code,
                    qty=qty,
                    reason=reason or None,
                    operator=operator or None,
                    tx_time=datetime.now().isoformat(timespec="seconds"),
                )
                st.success("出庫を記録しました")
                st.rerun()

st.divider()

st.subheader("最近の在庫イベント")
rows = get_recent_transactions(limit=20)

if rows:
    table_data = [dict(row) for row in rows]
    st.dataframe(table_data, width="stretch")
else:
    st.info("まだ在庫イベントはありません")
