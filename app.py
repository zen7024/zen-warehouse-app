import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import streamlit_authenticator as stauth
import yaml
from yaml import SafeLoader
from streamlit_qrcode_scanner import qrcode_scanner as qr_scanner  # type: ignore

# ページ設定
st.set_page_config(
    page_title="倉庫分析アプリ📦",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="auto"
)

st.title("📦 小さな倉庫分析アプリ")

# 認証設定
if "authenticator" not in st.session_state:
    credentials = {
        "usernames": {
            "zen": {
                "email": "zen@example.com",
                "name": "Zen",
                "password": stauth.Hasher.hash("password"),
            },
            "testuser": {
                "email": "test@example.com",
                "name": "テストユーザー",
                "password": stauth.Hasher.hash("testpass"),
            }
        }
    }
    st.session_state.authenticator = stauth.Authenticate(
        credentials,
        cookie_name="warehouse_app",
        key="abcd",
        cookie_expiry_days=1,
    )

authenticator = st.session_state.authenticator
authenticator.login(
    location="sidebar",
    fields={"Form name": "ログイン"}
)

# 認証状態を取得
authentication_status = st.session_state.get("authentication_status")
username = st.session_state.get("username")
name = st.session_state.get("name")

if authentication_status is None:
    st.warning("👈 サイドバーからログインしてください")
    st.stop()
elif authentication_status is False:
    st.error("ユーザー名またはパスワードが正しくありません")
    st.stop()

# ログアウトボタン
st.sidebar.write(f"👤 {name}")
if st.sidebar.button("ログアウト"):
    authenticator.logout(
        location="sidebar",
        button_name="ログアウトしました"
    )
    st.experimental_rerun()

# ファイルアップロード
uploaded = st.file_uploader(
    "在庫データ (CSV または Excel)",
    type=["csv", "xlsx", "xls"],
)

# データ読み込み
if uploaded:
    if uploaded.name.endswith(".csv"):
        df = pd.read_csv(uploaded)
    else:
        df = pd.read_excel(uploaded, engine="openpyxl")
else:
    st.info("サンプルデータを表示中 …")
    df = pd.DataFrame(
        {
            "商品ID": ["A01", "A02", "B01", "B02"],
            "商品名": ["ペン", "ノート", "箱", "テープ"],
            "在庫数": [23, 5, 12, 3],
            "ロケーション": ["東京", "大阪", "東京", "大阪"],
            "更新日": [
                "2025-06-01",
                "2025-06-01",
                "2025-06-02",
                "2025-06-02",
            ],
        }
    )

# 日付型変換
if "更新日" in df.columns:
    if pd.api.types.is_object_dtype(df["更新日"]):
        df["更新日"] = pd.to_datetime(df["更新日"])

# サイドバー設定
low_stock_threshold = st.sidebar.number_input(
    "在庫不足判定しきい値", min_value=0, value=10
)

# KPI
col1, col2, col3 = st.columns(3)
col1.metric("総商品数", len(df))
col2.metric("総在庫数", int(df["在庫数"].sum()))
col3.metric("在庫不足品目", int((df["在庫数"] < low_stock_threshold).sum()))

# ミニ在庫検索
st.markdown("### 🔍 ミニ在庫検索")
search_term = st.text_input("商品名またはIDで検索", "")

if search_term:
    result_df = df[df["商品名"].str.contains(search_term, case=False, na=False) |
                   df["商品ID"].str.contains(search_term, case=False, na=False)]
    if not result_df.empty:
        st.dataframe(result_df, hide_index=True, height=250)
    else:
        st.info("該当する商品が見つかりませんでした。")

# フィルター
locations = st.multiselect(
    "ロケーションを選択",
    options=sorted(df["ロケーション"].unique()),
    default=list(df["ロケーション"].unique()),
)

df_filtered = df[df["ロケーション"].isin(locations)]

# 在庫一覧テーブル
st.subheader("在庫一覧")
st.dataframe(
    df_filtered.style.apply(
        lambda x: [
            "background-color:#FFCDD2" if v < low_stock_threshold else ""
            for v in x
        ],
        subset=["在庫数"],
    ),
    hide_index=True,
    height=350,
)

# 操作履歴用リスト初期化
if "ops" not in st.session_state:
    st.session_state.ops = []

# KPI算出直後に履歴登録
st.session_state.ops.append({
    "time": datetime.now().isoformat(timespec="seconds"),
    "action": "データ読み込み",
    "records": len(df)
})

# 可視化タブ
barcode_tab, inv_tab, trend_tab = st.tabs(["📷 バーコードスキャン", "ロケーション別在庫", "日別在庫推移"])

with barcode_tab:
    st.subheader("バーコード/QR 読み取り")
    try:
        code = qr_scanner("クリックしてカメラを起動")
        if code:
            st.success(f"読み取り結果: {code}")
            st.session_state.ops.append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "action": "スキャン",
                "code": code,
            })
    except ModuleNotFoundError:
        st.error("streamlit-qr-scanner がインストールされていません")

with inv_tab:
    fig_loc = px.bar(
        df_filtered.groupby("ロケーション")["在庫数"].sum().reset_index(),
        x="ロケーション",
        y="在庫数",
        title="ロケーション別 在庫総数",
        color="在庫数",
        color_continuous_scale="viridis",
    )
    st.plotly_chart(fig_loc, use_container_width=True)

with trend_tab:
    if "更新日" in df_filtered.columns:
        daily = (
            df_filtered.groupby(["更新日"])["在庫数"].sum().reset_index().sort_values("更新日")
        )
        fig_day = px.line(
            daily,
            x="更新日",
            y="在庫数",
            markers=True,
            title="日別 在庫推移",
        )
        st.plotly_chart(fig_day, use_container_width=True)
    else:
        st.info("📅『更新日』データがないため、日別在庫推移は表示できません。")

# 操作履歴ダウンロード
with st.sidebar:
    st.markdown("### 📝 操作履歴")
    if st.button("履歴をJSONでダウンロード"):
        import json, base64
        hist = json.dumps(st.session_state.ops, ensure_ascii=False, indent=2)
        b64 = base64.b64encode(hist.encode()).decode()
        href = f'<a href="data:application/json;base64,{b64}" download="ops_history.json">📥 ダウンロード</a>'
        st.markdown(href, unsafe_allow_html=True)

st.markdown("---")
st.caption(
    f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Powered by Streamlit"
)
