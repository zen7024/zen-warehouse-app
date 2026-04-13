import streamlit as st
import pandas as pd
from core.db import init_db, get_allocatable_stock_by_item

init_db()

st.title("📊 引当可能在庫")
st.write(
    "物理在庫から既存の未出荷引当（order_lines の qty_allocated - shipped_qty）を差し引き、"
    "新たに引き当て可能な数量を商品別に表示します。"
)

rows = get_allocatable_stock_by_item()

if rows:
    df = pd.DataFrame(rows)
    df = df.rename(
        columns={
            "item_code": "商品コード",
            "physical_qty": "物理在庫",
            "allocated_qty": "未出荷引当",
            "allocatable_qty": "引当可能在庫",
        }
    )
    st.metric("商品コード数", len(df))
    st.dataframe(df, width="stretch")
else:
    st.info("物理在庫も引当明細もまだありません")
