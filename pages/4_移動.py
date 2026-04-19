import streamlit as st
from datetime import datetime
from core.db import (
    init_db,
    get_current_stock,
    insert_transaction,
    get_recent_transactions,
    log_audit_event,
)

init_db()

st.title("🔄 移動処理")
st.write("あるロケーションの在庫を、別のロケーションへ移した記録を残します。")


def _stock_at(rows, item_code: str, location_code: str) -> float:
    for row in rows:
        d = dict(row)
        if d["item_code"] == item_code and d["location_code"] == location_code:
            return float(d["stock_qty"])
    return 0.0


with st.form("move_form"):
    col1, col2 = st.columns(2)

    with col1:
        item_code = st.text_input("商品コード", placeholder="ITEM-001")
        from_location = st.text_input("移動元ロケーション", placeholder="A-01-01")
        to_location = st.text_input("移動先ロケーション", placeholder="B-02-02")
        qty = st.number_input("数量", min_value=0.0, step=1.0)

    with col2:
        operator = st.text_input("作業者", placeholder="zen")
        reason = st.text_input("理由", value="ロケーション間移動")

    submitted = st.form_submit_button("移動を記録")

    if submitted:
        item_code = item_code.strip()
        from_location = from_location.strip()
        to_location = to_location.strip()
        operator = operator.strip()
        reason = reason.strip()

        if not item_code:
            st.error("商品コードを入力してください")
        elif not from_location:
            st.error("移動元ロケーションを入力してください")
        elif not to_location:
            st.error("移動先ロケーションを入力してください")
        elif from_location == to_location:
            st.error("移動元と移動先が同じです。別のロケーションを指定してください")
        elif qty <= 0:
            st.error("数量は0より大きくしてください")
        else:
            stock_rows = get_current_stock()
            available = _stock_at(stock_rows, item_code, from_location)

            if qty > available:
                st.error(f"在庫不足です。移動元の現在庫: {available}")
            else:
                tx_time = datetime.now().isoformat(timespec="seconds")
                insert_transaction(
                    tx_type="move_out",
                    item_code=item_code,
                    location_code=from_location,
                    qty=qty,
                    reason=reason or None,
                    operator=operator or None,
                    tx_time=tx_time,
                )
                insert_transaction(
                    tx_type="move_in",
                    item_code=item_code,
                    location_code=to_location,
                    qty=qty,
                    reason=reason or None,
                    operator=operator or None,
                    tx_time=tx_time,
                )
                log_audit_event(
                    event_type="MOVE",
                    user_id=operator or None,
                    item_code=item_code,
                    before_value={
                        "from_location": from_location,
                        "from_stock_qty": float(available),
                    },
                    after_value={
                        "from_location": from_location,
                        "to_location": to_location,
                        "qty": float(qty),
                        "from_stock_qty": float(available) - float(qty),
                        "reason": reason or None,
                        "tx_time": tx_time,
                    },
                    free_note="移動処理",
                )
                st.success("移動を記録しました")
                st.rerun()

st.divider()

st.subheader("最近の在庫イベント")
rows = get_recent_transactions(limit=20)

if rows:
    table_data = [dict(row) for row in rows]
    st.dataframe(table_data, width="stretch")
else:
    st.info("まだ在庫イベントはありません")
