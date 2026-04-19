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

st.title("📋 棚卸差異処理")
st.write("実棚数とシステム上の現在庫の差を記録し、在庫を合わせます。")
# TODO(A-06): 別ロケ候補が見つからないケースを差異処理へ接続する余地あり
# TODO(A-06): 将来、差異理由コードや状態管理（HOLD/REALLOC_PENDING）との連携を追加


def _stock_at(rows, item_code: str, location_code: str) -> float:
    for row in rows:
        d = dict(row)
        if d["item_code"] == item_code and d["location_code"] == location_code:
            return float(d["stock_qty"])
    return 0.0


with st.form("count_adjust_form"):
    col1, col2 = st.columns(2)

    with col1:
        item_code = st.text_input("商品コード", placeholder="ITEM-001")
        location_code = st.text_input("ロケーション", placeholder="A-01-01")
        physical_qty = st.number_input("実棚数", min_value=0.0, step=1.0)

    with col2:
        operator = st.text_input("作業者", placeholder="zen")
        reason = st.text_input("理由", value="棚卸差異調整")

    submitted = st.form_submit_button("差異を記録")

    if submitted:
        item_code = item_code.strip()
        location_code = location_code.strip()
        operator = operator.strip()
        reason = reason.strip()

        if not item_code:
            st.error("商品コードを入力してください")
        elif not location_code:
            st.error("ロケーションを入力してください")
        else:
            stock_rows = get_current_stock()
            book_qty = _stock_at(stock_rows, item_code, location_code)
            delta = physical_qty - book_qty

            if delta == 0:
                st.info("差異なし（実棚数と現在庫が一致しています）。保存しませんでした。")
            else:
                tx_type = "count_plus" if delta > 0 else "count_minus"
                qty = abs(delta)
                tx_time = datetime.now().isoformat(timespec="seconds")
                insert_transaction(
                    tx_type=tx_type,
                    item_code=item_code,
                    location_code=location_code,
                    qty=qty,
                    reason=reason or None,
                    operator=operator or None,
                    tx_time=tx_time,
                )
                log_audit_event(
                    event_type="COUNT_DIFF",
                    user_id=operator or None,
                    item_code=item_code,
                    location_code=location_code,
                    before_value={"book_qty": float(book_qty)},
                    after_value={
                        "physical_qty": float(physical_qty),
                        "delta": float(delta),
                        "qty": float(qty),
                        "tx_type": tx_type,
                        "reason": reason or None,
                        "tx_time": tx_time,
                    },
                    free_note="棚卸差異処理",
                )
                st.success(
                    f"棚卸差異を記録しました（現在庫 {book_qty:g} → 実棚 {physical_qty:g}、"
                    f"{'増' if delta > 0 else '減'} {qty:g}）"
                )
                st.rerun()

st.divider()

st.subheader("最近の在庫イベント")
rows = get_recent_transactions(limit=20)

if rows:
    table_data = [dict(row) for row in rows]
    st.dataframe(table_data, width="stretch")
else:
    st.info("まだ在庫イベントはありません")
