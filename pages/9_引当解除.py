import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    list_orders_with_releasable_allocations,
    get_order_lines_shipment_view,
    release_allocation_for_line,
)

init_db()

st.title("🔓 引当解除")
st.write(
    "出荷指示の明細について、**未出荷の引当**だけを取り消します。"
    "出荷確定済み（出荷済数量に含まれる分）は解除できません。"
)

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
        "qty_unshipped": "解除可能数量",
    }
)
st.dataframe(df, width="stretch")

st.divider()
st.subheader("解除操作")

any_releasable = False
for row in rows:
    lid = row["line_id"]
    item = row["item_code"]
    releasable = float(row["qty_unshipped"])
    if releasable <= 1e-9:
        continue
    any_releasable = True

    st.markdown(f"**明細 ID {lid}** ・ {item}")
    c1, c2, c3 = st.columns([2, 1, 1])
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
        if st.button("指定数量を解除", key=f"release_btn_{lid}"):
            ok, msg = release_allocation_for_line(lid, qty_in)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    with c3:
        if st.button("全解除", key=f"release_all_{lid}"):
            ok, msg = release_allocation_for_line(lid, releasable)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

if not any_releasable:
    st.info("この指示には解除可能な未出荷引当がありません。")
