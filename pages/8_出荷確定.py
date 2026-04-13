import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    list_orders_for_ship_confirm,
    get_order_lines_shipment_view,
    get_allocation_details_for_order,
    confirm_shipment_for_order,
)

init_db()

st.title("🚚 出荷確定")
st.write(
    "選択した出荷指示について、引当済みかつ未出荷の数量を "
    "`inventory_transactions` の出庫（issue）として記録し、明細の出荷済数量を更新します。"
)
st.caption(
    "新規の引当はロケーション別に記録されます。出荷確定ではそのロケーションから issue します。"
    "引当明細が無い旧データのみ、集約コード（__SHIP__）へ出庫します。"
)

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

rows = get_order_lines_shipment_view(order_id)

if not rows:
    st.warning("この指示に明細がありません")
    st.stop()

df = pd.DataFrame([dict(row) for row in rows])
df = df.rename(
    columns={
        "line_id": "明細ID",
        "item_code": "商品コード",
        "qty_required": "必要数",
        "qty_allocated": "引当済",
        "shipped_qty": "出荷済",
        "qty_unshipped": "未出荷数量",
    }
)
st.dataframe(df, width="stretch")

ad_rows = get_allocation_details_for_order(order_id)
if ad_rows:
    with st.expander("ロケーション別引当・未出荷内訳", expanded=True):
        df_ad = pd.DataFrame([dict(row) for row in ad_rows])
        df_ad = df_ad.rename(
            columns={
                "line_id": "明細ID",
                "item_code": "商品コード",
                "location_code": "ロケーション",
                "allocated_qty": "引当数量",
                "shipped_qty": "出荷済",
                "qty_unshipped": "未出荷",
            }
        )
        st.dataframe(df_ad, width="stretch")
else:
    st.info("この指示にはロケーション別引当明細がありません（登録当時の旧形式の可能性）。出庫は __SHIP__ に集約されます。")

has_unshipped = any(float(dict(row)["qty_unshipped"]) > 0 for row in rows)
line_ship_qty_map = {}

if has_unshipped:
    st.subheader("今回出荷数量")
    st.caption("各明細の未出荷数量を上限に、今回出荷する数量を指定してください。")
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

st.divider()
operator = st.text_input("作業者", placeholder="任意")
reason = st.text_input("備考（出庫トランザクションの理由に含まれます）", value="出荷確定")

if st.button("出荷確定を実行", disabled=not has_unshipped, type="primary"):
    total_ship_qty = sum(float(v) for v in line_ship_qty_map.values())
    if total_ship_qty <= 0:
        st.error("今回出荷数量がすべて0です。1明細以上に数量を指定してください。")
        st.stop()
    ok, msg, _ = confirm_shipment_for_order(
        order_id,
        line_ship_qty_map=line_ship_qty_map,
        operator=operator.strip() or None,
        reason=reason.strip() or None,
    )
    if ok:
        st.success(msg)
        st.rerun()
    else:
        st.error(msg)

if not has_unshipped:
    st.info("この指示は未出荷の引当がありません（すべて出荷済み、または引当ゼロです）。")
