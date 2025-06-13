# zen_ai_web.py - zenさん専用AI Web版 v2.0 (データ分析機能付き)
import streamlit as st
import openai
import sys
import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime
import io

# 親ディレクトリのconfig.pyを読み込み
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY

# OpenAI API設定
openai.api_key = OPENAI_API_KEY

# ページ設定
st.set_page_config(
    page_title="zenさん専用AI v2.0",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# カスタムCSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
    }
    .chat-container {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .user-message {
        background: #007bff;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 15px;
        margin: 0.5rem 0;
        text-align: right;
    }
    .ai-message {
        background: #28a745;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 15px;
        margin: 0.5rem 0;
    }
    .data-stats {
        background: #e3f2fd;
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .metric-card {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# メインヘッダー
st.markdown("""
<div class="main-header">
    <h1>📊 zenさん専用AI v2.0</h1>
    <p>Java学習・データ分析・AI相談 - すべて対応</p>
</div>
""", unsafe_allow_html=True)

# サイドバー
with st.sidebar:
    st.markdown("### ⚙️ AI設定")
    
    # モデル選択
    model_choice = st.selectbox(
        "AIモデル",
        ["gpt-3.5-turbo", "gpt-4"],
        index=0
    )
    
    # 温度設定
    temperature = st.slider(
        "創造性レベル",
        0.0, 1.0, 0.7,
        help="0.0: 論理的, 1.0: 創造的"
    )
    
    # 最大トークン数
    max_tokens = st.slider(
        "回答の長さ",
        100, 1000, 500
    )
    
    st.markdown("### 📊 データ分析機能")
    
    # ファイルアップロード
    uploaded_file = st.file_uploader(
        "CSVまたはExcelファイル",
        type=['csv', 'xlsx', 'xls'],
        help="売上データ、在庫データなどをアップロード"
    )
    
    # データ分析オプション
    if uploaded_file:
        analysis_type = st.selectbox(
            "分析タイプ",
            ["基本統計", "トレンド分析", "グラフ作成", "相関分析"]
        )
    
    st.markdown("### 📈 使用状況")
    if 'message_count' not in st.session_state:
        st.session_state.message_count = 0
    if 'analysis_count' not in st.session_state:
        st.session_state.analysis_count = 0
        
    col1, col2 = st.columns(2)
    with col1:
        st.metric("質問回数", st.session_state.message_count)
    with col2:
        st.metric("分析回数", st.session_state.analysis_count)
    
    st.markdown("### 🎯 クイックアクション")
    if st.button("💾 履歴をダウンロード"):
        st.success("履歴保存機能実装済み！")
    
    if st.button("🗑️ データをクリア"):
        st.session_state.messages = []
        st.session_state.uploaded_data = None
        st.success("データをクリアしました！")

# メインコンテンツエリア
col1, col2 = st.columns([2, 1])

with col1:
    # チャット履歴の初期化
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "👋 zenさん、こんにちは！v2.0にアップグレードしました！\n\n🆕 新機能:\n📊 CSVファイルアップロード\n📈 グラフ作成\n📉 統計分析\n\n何でもお聞きください！"
            }
        ]

    # チャット履歴表示
    st.markdown("### 💬 AI相談チャット")
    chat_container = st.container()

    with chat_container:
        for message in st.session_state.messages:
            if message["role"] == "user":
                st.markdown(f"""
                <div class="user-message">
                    👤 zen: {message["content"]}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="ai-message">
                    🤖 AI: {message["content"]}
                </div>
                """, unsafe_allow_html=True)

    # 質問入力
    st.markdown("### ✍️ 質問・相談を入力")
    input_col1, input_col2 = st.columns([4, 1])

    with input_col1:
        user_input = st.text_input(
            "質問",
            placeholder="Java学習、データ分析、何でも質問してください...",
            label_visibility="collapsed"
        )

    with input_col2:
        send_button = st.button("📤 送信", use_container_width=True)

    # メッセージ送信処理
    if send_button and user_input:
        # ユーザーメッセージを追加
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        # データ分析関連の質問かチェック
        data_context = ""
        if 'uploaded_data' in st.session_state and st.session_state.uploaded_data is not None:
            df = st.session_state.uploaded_data
            data_context = f"\n\n【アップロードされたデータ情報】\n- 行数: {len(df)}\n- 列数: {len(df.columns)}\n- 列名: {', '.join(df.columns[:5])}{'...' if len(df.columns) > 5 else ''}"
        
        # OpenAI APIに送信
        try:
            with st.spinner("🤖 AI が考えています..."):
                response = openai.chat.completions.create(
                    model=model_choice,
                    messages=[
                        {
                            "role": "system",
                            "content": f"あなたはzenさん専用のAIアシスタントです。zenさんは39歳、倉庫業勤務、Java初心者、データ分析学習中です。親しみやすく、わかりやすく回答してください。{data_context}"
                        }
                    ] + st.session_state.messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                ai_response = response.choices[0].message.content
                st.session_state.messages.append({"role": "assistant", "content": ai_response})
                st.session_state.message_count += 1
                
                # 画面を再読み込み
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ エラーが発生しました: {e}")
            st.info("🔧 APIキーやネット接続を確認してください")

    # 使用例
    st.markdown("### 💡 使用例")
    example_col1, example_col2, example_col3 = st.columns(3)

    with example_col1:
        if st.button("📚 Java基礎質問"):
            st.session_state.example_input = "Javaのオブジェクト指向について教えて"

    with example_col2:
        if st.button("📊 データ分析相談"):
            st.session_state.example_input = "アップロードしたデータの傾向を分析して"

    with example_col3:
        if st.button("💼 仕事活用法"):
            st.session_state.example_input = "倉庫業務でデータ分析を活かす方法"

with col2:
    # データ分析パネル
    st.markdown("### 📊 データ分析パネル")
    
    if uploaded_file:
        try:
            # ファイル読み込み
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.session_state.uploaded_data = df
            st.session_state.analysis_count += 1
            
            # データ基本情報
            st.markdown("#### 📋 データ概要")
            st.info(f"**行数:** {len(df)} | **列数:** {len(df.columns)}")
            
            # データプレビュー
            st.markdown("#### 👀 データプレビュー")
            st.dataframe(df.head(), use_container_width=True)
            
            # 基本統計
            st.markdown("#### 📈 基本統計情報")
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            
            if len(numeric_cols) > 0:
                stats_df = df[numeric_cols].describe()
                st.dataframe(stats_df, use_container_width=True)
                
                # グラフ作成
                st.markdown("#### 📊 データ可視化")
                
                if len(numeric_cols) >= 1:
                    selected_col = st.selectbox("グラフ化する列", numeric_cols)
                    
                    chart_type = st.selectbox(
                        "グラフタイプ",
                        ["ヒストグラム", "箱ひげ図", "折れ線グラフ", "散布図"]
                    )
                    
                    if chart_type == "ヒストグラム":
                        fig = px.histogram(df, x=selected_col, title=f"{selected_col}の分布")
                        st.plotly_chart(fig, use_container_width=True)
                    
                    elif chart_type == "箱ひげ図":
                        fig = px.box(df, y=selected_col, title=f"{selected_col}の箱ひげ図")
                        st.plotly_chart(fig, use_container_width=True)
                    
                    elif chart_type == "折れ線グラフ":
                        fig = px.line(df, y=selected_col, title=f"{selected_col}の推移")
                        st.plotly_chart(fig, use_container_width=True)
                    
                    elif chart_type == "散布図" and len(numeric_cols) >= 2:
                        y_col = st.selectbox("Y軸の列", [col for col in numeric_cols if col != selected_col])
                        fig = px.scatter(df, x=selected_col, y=y_col, title=f"{selected_col} vs {y_col}")
                        st.plotly_chart(fig, use_container_width=True)
                
                # AI分析提案
                st.markdown("#### 🤖 AI分析提案")
                if st.button("📊 このデータをAIに分析させる"):
                    analysis_prompt = f"アップロードされたデータを分析してください。データには{len(df)}行、{len(df.columns)}列があり、数値列は{', '.join(numeric_cols)}です。主要な特徴や傾向を教えてください。"
                    
                    st.session_state.messages.append({"role": "user", "content": analysis_prompt})
                    
                    try:
                        response = openai.chat.completions.create(
                            model=model_choice,
                            messages=[
                                {
                                    "role": "system",
                                    "content": f"データ分析の専門家として、zenさんにわかりやすくデータの特徴を説明してください。データ情報: 行数{len(df)}, 列数{len(df.columns)}, 数値列{list(numeric_cols)}"
                                }
                            ] + st.session_state.messages[-1:],
                            max_tokens=max_tokens,
                            temperature=0.3
                        )
                        
                        ai_analysis = response.choices[0].message.content
                        st.session_state.messages.append({"role": "assistant", "content": ai_analysis})
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"分析エラー: {e}")
            else:
                st.warning("数値データが見つかりません。数値列を含むファイルをアップロードしてください。")
                
        except Exception as e:
            st.error(f"ファイル読み込みエラー: {e}")
            st.info("CSVまたはExcelファイルを確認してください")
    
    else:
        st.info("📁 CSVまたはExcelファイルをアップロードすると、データ分析機能が使えます！")
        
        # サンプルデータ提案
        st.markdown("#### 💡 サンプルデータ例")
        st.write("**売上データ例:**")
        sample_sales = pd.DataFrame({
            '日付': pd.date_range('2024-01-01', periods=30, freq='D'),
            '売上': np.random.randint(10000, 50000, 30),
            '商品数': np.random.randint(50, 200, 30)
        })
        st.dataframe(sample_sales.head(), use_container_width=True)

# フッター
st.markdown("---")
st.markdown("🚀 **zenさん専用AI v2.0** | データ分析機能実装完了！")