import streamlit as st
import pandas as pd
from core.db import init_db, get_all_items, register_item, update_item_status

init_db()

st.title("🏷️ 商品登録")

# ---- 登録フォーム ----
st.subheader("新規商品登録")

with st.form("item_registration_form", clear_on_submit=True):
    item_code = st.text_input("商品コード *", placeholder="例: ITEM-001")
    item_name = st.text_input("商品名 *", placeholder="例: ダンボール箱 A4")
    unit = st.selectbox("単位", ["pcs", "kg", "m", "L", "box", "set"])
    is_active = st.radio("状態", ["有効", "無効"], index=0)
    submitted = st.form_submit_button("登録する")

if submitted:
    code = item_code.strip()
    name = item_name.strip()
    if not code:
        st.error("商品コードを入力してください。")
    elif not name:
        st.error("商品名を入力してください。")
    else:
        result = register_item(
            item_code=code,
            item_name=name,
            unit=unit,
            is_active=1 if is_active == "有効" else 0,
        )
        if result is None:
            st.error(f"商品コード「{code}」はすでに登録されています。")
        else:
            st.success(f"商品「{name}（{code}）」を登録しました。")

st.divider()

# ---- 商品一覧 ----
st.subheader("登録済み商品一覧")

search = st.text_input("商品コード / 商品名で絞り込み（部分一致）", value="")

items = get_all_items()
df = pd.DataFrame(items) if items else pd.DataFrame(columns=["item_code", "item_name", "unit", "is_active"])

if not df.empty:
    if search.strip():
        needle = search.strip().lower()
        mask = df["item_code"].str.lower().str.contains(needle) | df["item_name"].str.lower().str.contains(needle)
        df = df[mask]

    df_display = df.rename(columns={
        "item_code": "商品コード",
        "item_name": "商品名",
        "unit": "単位",
        "is_active": "状態",
    }).copy()
    df_display["状態"] = df_display["状態"].map({1: "有効", 0: "無効"})

    st.metric("件数", len(df_display))
    st.dataframe(df_display, use_container_width=True)
else:
    st.info("登録済み商品はまだありません。")

st.divider()

# ---- 有効/無効 切り替え ----
st.subheader("有効 / 無効 切り替え")

all_items = get_all_items()
if all_items:
    options = {f"{r['item_code']}　{r['item_name']}": r for r in all_items}
    selected_label = st.selectbox("対象商品", list(options.keys()))
    selected = options[selected_label]
    current_status = "有効" if selected["is_active"] == 1 else "無効"
    st.write(f"現在の状態：**{current_status}**")

    new_status = st.radio("変更後の状態", ["有効", "無効"],
                          index=0 if selected["is_active"] == 1 else 1,
                          key="status_toggle")
    if st.button("状態を更新する"):
        update_item_status(selected["item_code"], 1 if new_status == "有効" else 0)
        st.success(f"「{selected['item_code']}」の状態を「{new_status}」に更新しました。")
        st.rerun()
else:
    st.info("商品が登録されていません。")
