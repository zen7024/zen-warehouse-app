import streamlit as st
import pandas as pd
from core.db import get_current_stock

st.title("📦 現在庫")

st.write("在庫イベントから集計した現在庫を表示します。")

rows = get_current_stock()

if rows:
    df = pd.DataFrame([dict(row) for row in rows])
    df = df.rename(columns={
        "item_code": "商品コード",
        "location_code": "ロケーション",
        "stock_qty": "現在庫数",
    })

    st.metric("在庫明細数", len(df))
    st.dataframe(df, width="stretch")
else:
    st.info("現在庫データはまだありません")