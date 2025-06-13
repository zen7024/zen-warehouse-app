# zen_ai_web.py - zenさん専用AI v3.0 完全版
import streamlit as st
import openai
import sys
import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
import json
import io
import base64
import requests  # Notion、Slack、Webhookの連携に必要
# pyaudioは不要 - Web Speech APIを使用
import pymysql
from pymysql.cursors import DictCursor

# 親ディレクトリのconfig.pyを読み込み
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY

# OpenAI API設定
openai.api_key = OPENAI_API_KEY

# Notion API設定
NOTION_API_KEY = "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"
NOTION_VERSION = "2022-06-28"

# Notion APIヘッダー
notion_headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION
}

# DB設定
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "7024")
DB_NAME = os.getenv("DB_NAME", "zen_ai_db")

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True
    )

def init_db():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            role VARCHAR(20),
            content TEXT,
            timestamp DATETIME
        ) CHARACTER SET utf8mb4
        """)
    conn.close()

def save_message_db(role: str, content: str, ts: str):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_history (role, content, timestamp) VALUES (%s, %s, %s)",
                (role, content, ts)
            )
        conn.close()
    except Exception as e:
        st.error(f"DB保存エラー: {e}")

def load_recent_messages(limit: int = 50):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, timestamp FROM chat_history ORDER BY id DESC LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
        conn.close()
        return list(reversed(rows))  # 新しい→古い順を逆転
    except Exception as e:
        st.error(f"DB読み込みエラー: {e}")
        return []

# DB初期化
init_db()

# ページ設定
st.set_page_config(
    page_title="zenさん専用AI v3.0",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# セッション状態の初期化
if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'learning_progress' not in st.session_state:
    st.session_state.learning_progress = {
        'java_basics': 0,
        'data_analysis': 0,
        'ai_development': 0,
        'total_study_time': 0,
        'goals': []
    }
if 'user_preferences' not in st.session_state:
    st.session_state.user_preferences = {
        'voice_enabled': True,
        'notifications': True,
        'auto_save': True,
        'theme': 'dark'
    }

# テーマ設定
def get_theme_colors(theme):
    if theme == 'dark':
        return {
            'primary': '#667eea',
            'secondary': '#764ba2',
            'background': '#1e1e1e',
            'surface': '#2d2d2d',
            'text': '#ffffff',
            'accent': '#4CAF50'
        }
    else:
        return {
            'primary': '#2196F3',
            'secondary': '#FF9800',
            'background': '#ffffff',
            'surface': '#f5f5f5',
            'text': '#333333',
            'accent': '#4CAF50'
        }

theme_colors = get_theme_colors(st.session_state.theme)

# カスタムCSS（テーマ対応）
st.markdown(f"""
<style>
    .stApp {{
        background-color: {theme_colors['background']};
        color: {theme_colors['text']};
    }}
    .main-header {{
        background: linear-gradient(90deg, {theme_colors['primary']} 0%, {theme_colors['secondary']} 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }}
    .chat-container {{
        background: {theme_colors['surface']};
        padding: 1rem;
        border-radius: 15px;
        margin: 1rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }}
    .user-message {{
        background: {theme_colors['primary']};
        color: white;
        padding: 0.8rem 1.2rem;
        border-radius: 20px;
        margin: 0.5rem 0;
        text-align: right;
        animation: slideInRight 0.3s ease-out;
    }}
    .ai-message {{
        background: {theme_colors['accent']};
        color: white;
        padding: 0.8rem 1.2rem;
        border-radius: 20px;
        margin: 0.5rem 0;
        animation: slideInLeft 0.3s ease-out;
    }}
    .feature-card {{
        background: {theme_colors['surface']};
        padding: 1.5rem;
        border-radius: 12px;
        margin: 1rem 0;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        border: 1px solid rgba(255,255,255,0.1);
    }}
    .progress-bar {{
        background: {theme_colors['surface']};
        border-radius: 10px;
        overflow: hidden;
        margin: 0.5rem 0;
    }}
    .progress-fill {{
        background: linear-gradient(90deg, {theme_colors['primary']}, {theme_colors['accent']});
        height: 20px;
        border-radius: 10px;
        transition: width 0.3s ease;
    }}
    .metric-card {{
        background: {theme_colors['surface']};
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        border: 2px solid {theme_colors['primary']};
    }}
    .voice-button {{
        background: linear-gradient(45deg, #FF6B6B, #4ECDC4);
        border: none;
        padding: 1rem;
        border-radius: 50%;
        color: white;
        font-size: 1.5rem;
        cursor: pointer;
        animation: pulse 2s infinite;
    }}
    @keyframes slideInRight {{
        from {{ transform: translateX(100%); opacity: 0; }}
        to {{ transform: translateX(0); opacity: 1; }}
    }}
    @keyframes slideInLeft {{
        from {{ transform: translateX(-100%); opacity: 0; }}
        to {{ transform: translateX(0); opacity: 1; }}
    }}
    @keyframes pulse {{
        0% {{ transform: scale(1); }}
        50% {{ transform: scale(1.05); }}
        100% {{ transform: scale(1); }}
    }}
    .notification {{
        position: fixed;
        top: 20px;
        right: 20px;
        background: {theme_colors['accent']};
        color: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        z-index: 1000;
    }}
</style>
""", unsafe_allow_html=True)

# PWA対応のmanifest.json生成
def generate_manifest():
    manifest = {
        "name": "zenさん専用AI",
        "short_name": "zenAI",
        "description": "zenさんの学習・仕事をサポートするAIアシスタント",
        "start_url": "/",
        "display": "standalone",
        "background_color": theme_colors['background'],
        "theme_color": theme_colors['primary'],
        "icons": [
            {
                "src": "data:image/svg+xml;base64," + base64.b64encode("""
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="50" fill="#667eea"/>
                    <text x="50" y="55" font-family="Arial" font-size="30" fill="white" text-anchor="middle">🧠</text>
                </svg>
                """.encode()).decode(),
                "sizes": "192x192",
                "type": "image/svg+xml"
            }
        ]
    }
    return json.dumps(manifest)

# Service Worker JavaScript
service_worker_js = """
const CACHE_NAME = 'zen-ai-v3';
const urlsToCache = [
    '/',
    '/static/css/main.css',
    '/static/js/main.js'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(urlsToCache))
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    return response;
                }
                return fetch(event.request);
            })
    );
});
"""

# メインヘッダー
st.markdown(f"""
<div class="main-header">
    <h1>🧠 zenさん専用AI v3.0 完全版</h1>
    <p>🎯 学習管理 | 📊 データ分析 | 🎤 音声対応 | 📱 PWA対応</p>
    <small>オフライン対応・完全個人特化型AIアシスタント</small>
</div>
""", unsafe_allow_html=True)

# サイドバー
with st.sidebar:
    st.markdown("### ⚙️ AI設定")
    
    # テーマ切り替え
    new_theme = st.selectbox(
        "🎨 テーマ",
        ["dark", "light"],
        index=0 if st.session_state.theme == "dark" else 1
    )
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.rerun()
    
    # モデル選択
    model_choice = st.selectbox(
        "🤖 AIモデル",
        ["gpt-3.5-turbo", "gpt-4"],
        index=0
    )
    
    # 音声機能
    st.markdown("### 🎤 音声機能")
    voice_enabled = st.checkbox("音声入力", value=st.session_state.user_preferences['voice_enabled'])
    voice_output = st.checkbox("音声出力", value=True)
    
    # 通知設定
    st.markdown("### 🔔 通知設定")
    notifications = st.checkbox("通知有効", value=st.session_state.user_preferences['notifications'])
    study_reminders = st.checkbox("学習リマインダー", value=True)
    
    # データ管理
    st.markdown("### 💾 データ管理")
    auto_save = st.checkbox("自動保存", value=st.session_state.user_preferences['auto_save'])
    
    if st.button("📥 履歴をダウンロード"):
        history_json = json.dumps(st.session_state.chat_history, ensure_ascii=False, indent=2)
        st.download_button(
            "💾 chat_history.json",
            history_json,
            "zen_ai_chat_history.json",
            "application/json"
        )
    
    if st.button("🗑️ 全データクリア"):
        st.session_state.chat_history = []
        st.session_state.messages = []
        st.success("データをクリアしました！")
    
    # 使用統計
    st.markdown("### 📊 使用統計")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("総チャット", len(st.session_state.chat_history))
    with col2:
        st.metric("学習時間", f"{st.session_state.learning_progress['total_study_time']:.1f}h")

# Notion連携機能
def notion_integration():
    st.markdown("### 📝 Notion連携")
    
    # データベース一覧取得
    if st.button("📋 Notionデータベース一覧を取得"):
        try:
            response = requests.post(
                "https://api.notion.com/v1/search",
                headers=notion_headers,
                json={
                    "filter": {
                        "value": "database",
                        "property": "object"
                    }
                }
            )
            
            if response.status_code == 200:
                databases = response.json().get("results", [])
                if databases:
                    st.success(f"✅ {len(databases)}件のデータベースを取得しました")
                    
                    # データベース一覧をテーブルで表示
                    db_data = []
                    for db in databases:
                        title_list = db.get("title", [])
                        if title_list and isinstance(title_list, list):
                            title = title_list[0].get("plain_text", "無題のデータベース")
                        else:
                            title = "無題のデータベース"
                        db_data.append({
                            "データベース名": title,
                            "データベースID": db.get("id"),
                            "作成日": db.get("created_time", "").split("T")[0]
                        })
                    
                    st.dataframe(pd.DataFrame(db_data))
                else:
                    st.info("アクセス可能なデータベースがありません。")
            else:
                st.error(f"❌ エラー: {response.status_code}\n{response.text}")
                
        except Exception as e:
            st.error(f"❌ 取得エラー: {e}")
    
    # データベースID入力
    notion_database_id = st.text_input("Notion Database ID", help="学習進捗を記録するデータベースID")
    
    if notion_database_id:
        if st.button("📊 Notionに学習進捗を送信"):
            try:
                data = {
                    "parent": {"database_id": notion_database_id},
                    "properties": {
                        "日付": {
                            "date": {"start": datetime.now().isoformat()}
                        },
                        "Java基礎": {
                            "number": st.session_state.learning_progress.get('java_basics', 0)
                        },
                        "データ分析": {
                            "number": st.session_state.learning_progress.get('data_analysis', 0)
                        },
                        "AI開発": {
                            "number": st.session_state.learning_progress.get('ai_development', 0)
                        }
                    }
                }
                
                response = requests.post(
                    "https://api.notion.com/v1/pages",
                    headers=notion_headers,
                    json=data
                )
                
                if response.status_code == 200:
                    st.success("✅ Notionに学習進捗を記録しました！")
                else:
                    st.error(f"❌ エラー: {response.status_code}")
                    
            except Exception as e:
                st.error(f"❌ 送信エラー: {e}")

# メインコンテンツ
tab1, tab2, tab3, tab4, tab5 = st.tabs(["💬 AIチャット", "📚 学習管理", "📊 データ分析", "🔗 アプリ連動", "⚙️ 設定"])

with tab1:
    # チャット履歴の初期化
    if "messages" not in st.session_state:
        recent_msgs = load_recent_messages(50)
        if recent_msgs:
            st.session_state.messages = recent_msgs
        else:
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": "🧠 zenさん、v3.0完全版へようこそ！\n\n🆕 新機能:\n🎤 音声入力・出力\n💾 永続データ保存\n🎨 テーマ変更\n📚 学習進捗管理\n🔔 通知システム\n📱 PWA対応\n\n何でもお聞きください！",
                    "timestamp": datetime.now().isoformat()
                }
            ]
        st.session_state.chat_history = st.session_state.messages.copy()

    # チャット履歴表示
    st.markdown("### 💬 AI相談チャット")
    
    # 音声入力ボタン
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if voice_enabled:
            st.markdown("""
            <div style="text-align: center; margin: 1rem 0;">
                <button class="voice-button" onclick="startVoiceInput()">🎤</button>
                <p>音声入力（クリックして話してください）</p>
            </div>
            """, unsafe_allow_html=True)

    chat_container = st.container()

    with chat_container:
        for message in st.session_state.messages:
            if message["role"] == "user":
                st.markdown(f"""
                <div class="user-message">
                    👤 zen: {message["content"]}
                    <small style="opacity: 0.7;">
                        {datetime.fromisoformat(message.get('timestamp', datetime.now().isoformat())).strftime('%H:%M')}
                    </small>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="ai-message">
                    🧠 AI: {message["content"]}
                    <small style="opacity: 0.7;">
                        {datetime.fromisoformat(message.get('timestamp', datetime.now().isoformat())).strftime('%H:%M')}
                    </small>
                </div>
                """, unsafe_allow_html=True)

    # チャット送信処理を関数化
    def send_message():
        user_input = st.session_state.chat_input
        if user_input:
            # ユーザーメッセージを追加
            user_message = {
                "role": "user", 
                "content": user_input,
                "timestamp": datetime.now().isoformat()
            }
            st.session_state.messages.append(user_message)
            st.session_state.chat_history.append(user_message)
            save_message_db("user", user_input, user_message["timestamp"])
            
            # OpenAI APIに送信
            try:
                with st.spinner("🧠 AI が考えています..."):
                    # 学習コンテキストを追加
                    context = f"""
                    zenさんの学習進捗:
                    - Java基礎: {st.session_state.learning_progress['java_basics']}%
                    - データ分析: {st.session_state.learning_progress['data_analysis']}%
                    - AI開発: {st.session_state.learning_progress['ai_development']}%
                    - 総学習時間: {st.session_state.learning_progress['total_study_time']}時間
                    """
                    
                    response = openai.chat.completions.create(
                        model=model_choice,
                        messages=[
                            {
                                "role": "system",
                                "content": f"あなたはzenさん専用の高度AIアシスタントです。zenさんは39歳、倉庫業勤務、プログラミング学習中です。親しみやすく、的確で実用的なアドバイスをしてください。{context}"
                            }
                        ] + st.session_state.messages,
                        max_tokens=800,
                        temperature=0.7
                    )
                    
                    ai_message = {
                        "role": "assistant",
                        "content": response.choices[0].message.content,
                        "timestamp": datetime.now().isoformat()
                    }
                    st.session_state.messages.append(ai_message)
                    st.session_state.chat_history.append(ai_message)
                    save_message_db("assistant", ai_message["content"], ai_message["timestamp"])
                    
                    # 学習時間を追加（概算）
                    st.session_state.learning_progress['total_study_time'] += 0.1
                    
                    # 入力欄をクリア（コールバック内なので安全）
                    st.session_state.chat_input = ""
                    
            except Exception as e:
                st.error(f"❌ エラーが発生しました: {e}")

    # チャット入力欄
    st.markdown("### ✍️ 質問・相談を入力")
    input_col1, input_col2 = st.columns([4, 1])

    with input_col1:
        user_input = st.text_input(
            "質問",
            placeholder="何でも質問してください...",
            label_visibility="collapsed",
            key="chat_input",
            on_change=send_message  # エンターキーで送信時のコールバック
        )

    with input_col2:
        if st.button("📤 送信", use_container_width=True):  # ボタンクリックでも送信
            send_message()

with tab2:
    st.markdown("### 📚 学習進捗管理")
    
    # 学習目標設定
    st.markdown("#### 🎯 今日の学習目標")
    goal_col1, goal_col2 = st.columns([3, 1])
    with goal_col1:
        new_goal = st.text_input("新しい目標", placeholder="例: Java配列を理解する")
    with goal_col2:
        if st.button("➕ 追加"):
            if new_goal:
                st.session_state.learning_progress['goals'].append({
                    'goal': new_goal,
                    'date': datetime.now().date().isoformat(),
                    'completed': False
                })
                st.success("目標を追加しました！")
    
    # 進捗表示
    st.markdown("#### 📈 学習進捗")
    
    progress_col1, progress_col2, progress_col3 = st.columns(3)
    
    with progress_col1:
        java_progress = st.slider("Java基礎", 0, 100, st.session_state.learning_progress['java_basics'])
        st.session_state.learning_progress['java_basics'] = java_progress
        
    with progress_col2:
        data_progress = st.slider("データ分析", 0, 100, st.session_state.learning_progress['data_analysis'])
        st.session_state.learning_progress['data_analysis'] = data_progress
        
    with progress_col3:
        ai_progress = st.slider("AI開発", 0, 100, st.session_state.learning_progress['ai_development'])
        st.session_state.learning_progress['ai_development'] = ai_progress
    
    # 進捗グラフ
    progress_data = pd.DataFrame({
        'スキル': ['Java基礎', 'データ分析', 'AI開発'],
        '進捗率': [java_progress, data_progress, ai_progress]
    })
    
    fig = px.bar(progress_data, x='スキル', y='進捗率', 
                 title="zenさんの学習進捗", color='進捗率',
                 color_continuous_scale='Viridis')
    st.plotly_chart(fig, use_container_width=True)
    
    # 目標一覧
    st.markdown("#### ✅ 目標達成状況")
    if st.session_state.learning_progress['goals']:
        for i, goal in enumerate(st.session_state.learning_progress['goals']):
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.write(f"📝 {goal['goal']}")
            with col2:
                if st.checkbox("完了", key=f"goal_{i}", value=goal['completed']):
                    st.session_state.learning_progress['goals'][i]['completed'] = True
            with col3:
                st.write(goal['date'])
    else:
        st.info("まだ目標が設定されていません。上記から目標を追加してください。")

with tab3:
    st.markdown("### 📊 データ分析機能")
    
    # ファイルアップロード
    uploaded_file = st.file_uploader(
        "📁 データファイルをアップロード",
        type=['csv', 'xlsx', 'xls'],
        help="分析したいデータファイルをドラッグ＆ドロップ"
    )
    
    if uploaded_file:
        try:
            # ファイル読み込み
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.success(f"✅ {uploaded_file.name} を読み込みました")
            
            # データ概要
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("データ行数", len(df))
            with col2:
                st.metric("列数", len(df.columns))
            with col3:
                st.metric("数値列", len(df.select_dtypes(include=[np.number]).columns))
            
            # データプレビュー
            st.markdown("#### 👀 データプレビュー")
            st.dataframe(df.head(10), use_container_width=True)
            
            # 分析オプション
            st.markdown("#### 🔍 分析オプション")
            analysis_col1, analysis_col2 = st.columns(2)
            
            with analysis_col1:
                numeric_cols = df.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    selected_col = st.selectbox("分析する列", numeric_cols)
                    
            with analysis_col2:
                chart_type = st.selectbox(
                    "可視化タイプ",
                    ["ヒストグラム", "箱ひげ図", "時系列", "相関マトリックス"]
                )
            
            # グラフ生成
            if len(numeric_cols) > 0:
                if chart_type == "ヒストグラム":
                    fig = px.histogram(df, x=selected_col, title=f"{selected_col}の分布")
                elif chart_type == "箱ひげ図":
                    fig = px.box(df, y=selected_col, title=f"{selected_col}の箱ひげ図")
                elif chart_type == "時系列":
                    fig = px.line(df.reset_index(), x=df.index, y=selected_col, title=f"{selected_col}の推移")
                elif chart_type == "相関マトリックス":
                    corr_matrix = df[numeric_cols].corr()
                    fig = px.imshow(corr_matrix, text_auto=True, title="相関マトリックス")
                
                st.plotly_chart(fig, use_container_width=True)
                
                # AI分析レポート
                if st.button("🧠 AIにこのデータを分析させる"):
                    with st.spinner("データを分析中..."):
                        stats = df[selected_col].describe()
                        analysis_prompt = f"""
                        データ分析レポートを作成してください：
                        - 列名: {selected_col}
                        - 平均: {stats['mean']:.2f}
                        - 標準偏差: {stats['std']:.2f}
                        - 最小値: {stats['min']}
                        - 最大値: {stats['max']}
                        zenさんにとって分かりやすく、実用的な洞察を提供してください。
                        """
                        
                        try:
                            response = openai.chat.completions.create(
                                model=model_choice,
                                messages=[{"role": "user", "content": analysis_prompt}],
                                max_tokens=500,
                                temperature=0.3
                            )
                            
                            st.markdown("#### 🧠 AI分析レポート")
                            st.info(response.choices[0].message.content)
                            
                        except Exception as e:
                            st.error(f"分析エラー: {e}")
                            
        except Exception as e:
            st.error(f"ファイル読み込みエラー: {e}")
    else:
        st.info("📁 分析したいCSVまたはExcelファイルをアップロードしてください")

with tab4:
    st.markdown("### 🔗 アプリ連動機能")
    notion_integration()  # Notion連携機能を呼び出し
    
    # アプリ連動タブの機能
    def app_integration_tab():
        st.markdown("#### 📱 連動可能アプリ")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            **📊 データ系**
            - Excel/Google Sheets
            - Notion
            - Airtable
            - CSV/JSON出力
            """)
        
        with col2:
            st.markdown("""
            **💬 コミュニケーション**
            - Slack
            - Teams
            - Discord
            - メール送信
            """)
        
        with col3:
            st.markdown("""
            **⏰ 自動化系**
            - iOS Shortcuts
            - IFTTT
            - Zapier
            - Webhook
            """)
        
        # Excel出力機能
        st.markdown("#### 📊 Excel出力機能")
        if st.button("📄 学習進捗をExcelで出力"):
            # 学習データをExcel形式で生成
            progress_data = pd.DataFrame({
                '日付': [datetime.now().strftime('%Y-%m-%d')],
                'Java基礎': [st.session_state.learning_progress.get('java_basics', 0)],
                'データ分析': [st.session_state.learning_progress.get('data_analysis', 0)],
                'AI開発': [st.session_state.learning_progress.get('ai_development', 0)],
                '総学習時間': [st.session_state.learning_progress.get('total_study_time', 0)]
            })
            
            # Excelファイル生成
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                progress_data.to_excel(writer, sheet_name='学習進捗', index=False)
                
                # チャット履歴も追加
                if st.session_state.chat_history:
                    chat_df = pd.DataFrame(st.session_state.chat_history)
                    chat_df.to_excel(writer, sheet_name='チャット履歴', index=False)
            
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 zenAI_progress.xlsx をダウンロード",
                data=excel_data,
                file_name=f"zenAI_progress_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        
        # Slack連携
        st.markdown("#### 💬 Slack連携")
        slack_webhook = st.text_input("Slack Webhook URL", type="password", help="SlackのIncoming Webhook URL")
        
        if slack_webhook:
            if st.button("📤 Slackに今日の学習報告"):
                try:
                    message = {
                        "text": f"🧠 zenさんの学習報告 {datetime.now().strftime('%Y-%m-%d')}",
                        "attachments": [
                            {
                                "color": "good",
                                "fields": [
                                    {
                                        "title": "Java基礎",
                                        "value": f"{st.session_state.learning_progress.get('java_basics', 0)}%",
                                        "short": True
                                    },
                                    {
                                        "title": "データ分析", 
                                        "value": f"{st.session_state.learning_progress.get('data_analysis', 0)}%",
                                        "short": True
                                    },
                                    {
                                        "title": "総学習時間",
                                        "value": f"{st.session_state.learning_progress.get('total_study_time', 0):.1f}時間",
                                        "short": True
                                    }
                                ]
                            }
                        ]
                    }
                    
                    response = requests.post(slack_webhook, json=message)
                    
                    if response.status_code == 200:
                        st.success("✅ Slackに学習報告を送信しました！")
                    else:
                        st.error(f"❌ エラー: {response.status_code}")
                        
                except Exception as e:
                    st.error(f"❌ 送信エラー: {e}")
        
        # iOS Shortcuts用JSON出力
        st.markdown("#### 📱 iOS Shortcuts連携")
        if st.button("📱 iOS Shortcuts用データ生成"):
            shortcuts_data = {
                "zen_ai_data": {
                    "timestamp": datetime.now().isoformat(),
                    "learning_progress": st.session_state.learning_progress,
                    "recent_chat": st.session_state.chat_history[-3:] if st.session_state.chat_history else [],
                    "summary": f"Java: {st.session_state.learning_progress.get('java_basics', 0)}%, データ分析: {st.session_state.learning_progress.get('data_analysis', 0)}%, 学習時間: {st.session_state.learning_progress.get('total_study_time', 0):.1f}h"
                }
            }
            
            json_str = json.dumps(shortcuts_data, ensure_ascii=False, indent=2)
            
            st.download_button(
                label="📥 zen_ai_shortcuts.json をダウンロード",
                data=json_str,
                file_name="zen_ai_shortcuts.json",
                mime="application/json"
            )
            
            st.info("""
            💡 **iOS Shortcuts使用方法:**
            1. このJSONファイルをiPhoneに保存
            2. Shortcuts アプリで「ファイルから辞書を取得」アクション使用
            3. Siriに「zenAIの進捗を教えて」で音声確認可能
            """)
        
        # Webhook設定
        st.markdown("#### 🔗 Webhook連携")
        webhook_url = st.text_input("Webhook URL", help="IFTTT、Zapier、または独自WebhookのURL")
        
        if webhook_url:
            webhook_event = st.selectbox(
                "送信するイベント",
                ["学習進捗更新", "目標達成", "チャット記録", "データ分析完了"]
            )
            
            if st.button(f"🚀 {webhook_event}をWebhookに送信"):
                try:
                    webhook_data = {
                        "event": webhook_event,
                        "timestamp": datetime.now().isoformat(),
                        "user": "zen",
                        "data": st.session_state.learning_progress
                    }
                    
                    response = requests.post(webhook_url, json=webhook_data)
                    
                    if response.status_code == 200:
                        st.success(f"✅ {webhook_event}をWebhookに送信しました！")
                    else:
                        st.error(f"❌ エラー: {response.status_code}")
                        
                except Exception as e:
                    st.error(f"❌ 送信エラー: {e}")

# 音声機能のJavaScript
st.markdown("""
<script>
function startVoiceInput() {
    if ('webkitSpeechRecognition' in window) {
        const recognition = new webkitSpeechRecognition();
        recognition.lang = 'ja-JP';
        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            document.querySelector('input[placeholder*="質問"]').value = transcript;
        };
        recognition.start();
    } else {
        alert('音声認識に対応していないブラウザです');
    }
}

// PWA登録
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js');
}
</script>
""", unsafe_allow_html=True)

# フッター
st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 1rem;">
    <h4>🧠 zenさん専用AI v3.5 アプリ連動機能追加版</h4>
    <p>🎯 オフライン対応 | 🎤 音声機能 | 📚 学習管理 | 📊 データ分析 | 🔗 アプリ連動</p>
    <small style="opacity: 0.7;">Powered by OpenAI • Made with ❤️ for zen</small>
</div>
""", unsafe_allow_html=True)