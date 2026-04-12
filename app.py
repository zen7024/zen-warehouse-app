import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import streamlit_authenticator as stauth
import yaml
from yaml import SafeLoader

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_SCANNER_AVAILABLE = True
except Exception:
    qrcode_scanner = None
    QR_SCANNER_AVAILABLE = False

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

# 操作履歴の初期化
if "ops" not in st.session_state:
    st.session_state.ops = []
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
    try:
        if uploaded.name.endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded, engine="openpyxl")
        st.success(f"✅ ファイル '{uploaded.name}' を正常に読み込みました")
        st.info(f"📊 データ形状: {df.shape[0]}行 × {df.shape[1]}列")
    except Exception as e:
        st.error(f"❌ ファイル読み込みエラー: {e}")
        st.stop()
else:
    st.info("📋 サンプルデータを表示中...")
    df = pd.DataFrame(
        {
            "商品ID": ["A01", "A02", "B01", "B02", "C01"],
            "商品名": ["ペン", "ノート", "箱", "テープ", "クリップ"],
            "在庫数": [23, 5, 12, 3, 15],
            "ロケーション": ["東京", "大阪", "東京", "大阪", "名古屋"],
            "更新日": [
                "2025-06-01",
                "2025-06-01",
                "2025-06-02",
                "2025-06-02",
                "2025-06-03",
            ],
        }
    )

# 列名マッピング機能
def normalize_column_names(df):
    """列名を標準形式にマッピング"""
    # 列名マッピング辞書
    column_mapping = {
        # 商品ID の別名
        "部番": "商品ID",
        "部品番号": "商品ID", 
        "製品番号": "商品ID",
        "品番": "商品ID",
        "コード": "商品ID",
        "ID": "商品ID",
        "商品コード": "商品ID",
        
        # 商品名 の別名
        "部品名": "商品名",
        "製品名": "商品名",
        "品名": "商品名",
        "名称": "商品名",
        "商品": "商品名",
        "アイテム名": "商品名",
        
        # 在庫数 の別名
        "数量": "在庫数",
        "在庫": "在庫数",
        "残数": "在庫数",
        "保有数": "在庫数",
        "現在庫": "在庫数",
        "在庫量": "在庫数",
        "QTY": "在庫数",
        "qty": "在庫数",
        
        # ロケーション の別名
        "所在地": "ロケーション",
        "棚番号": "ロケーション",
        "棚番": "ロケーション",
        "倉庫": "ロケーション",
        "場所": "ロケーション",
        "保管場所": "ロケーション",
        "位置": "ロケーション",
        "エリア": "ロケーション",
        "拠点": "ロケーション",
        "ゾーン": "ロケーション",
    }
    
    # 列名を正規化
    df_normalized = df.copy()
    renamed_columns = {}
    
    for old_col in df.columns:
        if old_col in column_mapping:
            new_col = column_mapping[old_col]
            renamed_columns[old_col] = new_col
    
    if renamed_columns:
        df_normalized = df_normalized.rename(columns=renamed_columns)
        st.info(f"🔄 列名を変換しました: {renamed_columns}")
    
    return df_normalized, renamed_columns

# 列名の正規化を実行
df, renamed_cols = normalize_column_names(df)

# デバッグ情報表示
with st.expander("🔍 デバッグ情報", expanded=False):
    st.write("**データフレームの形状:**", df.shape)
    st.write("**列名:**", list(df.columns))
    if renamed_cols:
        st.write("**変換された列名:**", renamed_cols)
    st.write("**データ型:**", df.dtypes.to_dict())
    st.write("**最初の5行:**")
    st.dataframe(df.head())

# データの列名チェックと修正
required_columns = ["商品ID", "商品名", "在庫数", "ロケーション"]
missing_columns = [col for col in required_columns if col not in df.columns]

if missing_columns:
    st.error(f"❌ 必要な列が見つかりません: {missing_columns}")
    
    # 列名マッピングの提案
    st.info("📝 以下の列名に対応しています:")
    
    st.markdown("**商品ID として認識される列名:**")
    st.write("部番, 部品番号, 製品番号, 品番, コード, ID, 商品コード")
    
    st.markdown("**商品名 として認識される列名:**")
    st.write("部品名, 製品名, 品名, 名称, 商品, アイテム名")
    
    st.markdown("**在庫数 として認識される列名:**")
    st.write("数量, 在庫, 残数, 保有数, 現在庫, 在庫量, QTY, qty")
    
    st.markdown("**ロケーション として認識される列名:**")
    st.write("所在地, 棚番号, 棚番, 倉庫, 場所, 保管場所, 位置, エリア, 拠点, ゾーン")
    
    # 利用可能な列を表示
    st.write("**現在のデータの列:**")
    for i, col in enumerate(df.columns, 1):
        st.write(f"{i}. {col}")
    
    # 手動マッピング機能
    st.markdown("### 🔧 手動列マッピング")
    if st.checkbox("手動で列をマッピングする"):
        available_columns = [""] + list(df.columns)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            id_col = st.selectbox("商品ID列を選択", available_columns)
        with col2:
            name_col = st.selectbox("商品名列を選択", available_columns)
        with col3:
            stock_col = st.selectbox("在庫数列を選択", available_columns)
        with col4:
            location_col = st.selectbox("ロケーション列を選択", available_columns)
        
        if all([id_col, name_col, stock_col, location_col]):
            # 手動マッピングを適用
            manual_mapping = {
                id_col: "商品ID",
                name_col: "商品名", 
                stock_col: "在庫数",
                location_col: "ロケーション"
            }
            df = df.rename(columns=manual_mapping)
            st.success(f"✅ 手動マッピングを適用しました: {manual_mapping}")
            st.experimental_rerun()
        else:
            st.warning("すべての列を選択してください")
            st.stop()
    else:
        st.stop()

# 日付型変換
if "更新日" in df.columns:
    try:
        if pd.api.types.is_object_dtype(df["更新日"]):
            df["更新日"] = pd.to_datetime(df["更新日"])
        st.success("✅ 更新日を日付型に変換しました")
    except Exception as e:
        st.warning(f"⚠️ 日付変換に失敗: {e}")

# 数値型変換（在庫数）
if "在庫数" in df.columns:
    try:
        df["在庫数"] = pd.to_numeric(df["在庫数"], errors="coerce")
        # NaNの処理
        if df["在庫数"].isna().any():
            na_count = df["在庫数"].isna().sum()
            st.warning(f"⚠️ 在庫数に数値以外のデータが{na_count}件ありました。0に置換します。")
            df["在庫数"] = df["在庫数"].fillna(0)
        st.success("✅ 在庫数を数値型に変換しました")
    except Exception as e:
        st.warning(f"⚠️ 在庫数の数値変換に失敗: {e}")

# サイドバー設定
low_stock_threshold = st.sidebar.number_input(
    "在庫不足判定しきい値", min_value=0, value=10
)

# KPI計算 - エラーハンドリング強化
try:
    total_products = len(df)
    
    # 在庫数列の存在確認
    if "在庫数" in df.columns:
        total_stock = int(df["在庫数"].sum())
        low_stock_items = int((df["在庫数"] < low_stock_threshold).sum())
    else:
        st.error("❌ '在庫数'列が見つかりません")
        total_stock = 0
        low_stock_items = 0
    
    # KPI表示
    col1, col2, col3 = st.columns(3)
    col1.metric("総商品数", total_products)
    col2.metric("総在庫数", total_stock)
    col3.metric("在庫不足品目", low_stock_items)
    
except Exception as e:
    st.error(f"❌ KPI計算エラー: {e}")
    st.write("デバッグ用データ:")
    st.write(df.head())
    st.write("列名:", list(df.columns))

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

# 可視化タブ
barcode_tab, inv_tab, trend_tab = st.tabs(["📷 バーコードスキャン", "ロケーション別在庫", "日別在庫推移"])

with barcode_tab:
    st.subheader("バーコード/QR 読み取り")

    if not QR_SCANNER_AVAILABLE:
        st.info("QRスキャナー機能は現在利用できません")
    else:
        try:
            code = qrcode_scanner(key="warehouse_qr_scanner")

            if code:
                st.success(f"読み取り結果: {code}")
                st.session_state.ops.append({
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "action": "スキャン",
                    "code": code,
                })
            else:
                st.info("カメラを起動してQR/バーコードを読み取ってください")

        except Exception as e:
            st.error(f"QRスキャナーエラー: {e}")

with inv_tab:
    # ロケーション別在庫グラフを表示（以前の tab1 処理を移動）
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
    f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Powered by Streamlit | ユーザー: {name}"
)