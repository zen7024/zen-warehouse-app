# zen_ai_web.py - zenさん専用AI Web版（セキュア版）
import streamlit as st
import openai
import os
from dotenv import load_dotenv
from datetime import datetime
import json

# 環境変数を読み込み
load_dotenv()

# APIキーを環境変数から取得
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    st.error("❌ OpenAI APIキーが設定されていません")
    st.info("💡 .envファイルにOPENAI_API_KEYを設定してください")
    st.stop()

# OpenAI API設定
openai.api_key = OPENAI_API_KEY

# ページ設定
st.set_page_config(
    page_title="zenさん専用AI 🤖",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 zenさん専用AI チャットボット")
st.markdown("**Java学習・業務相談・何でもお任せ！**")

# チャット履歴の初期化
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append({
        "role": "assistant",
        "content": "こんにちは！zenさん専用AIです。Java学習や業務について何でも聞いてください！"
    })

# チャット履歴の表示
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ユーザー入力
if prompt := st.chat_input("何か質問してください..."):
    # ユーザーメッセージを追加
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # ユーザーメッセージを表示
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # AI応答を生成
    with st.chat_message("assistant"):
        try:
            with st.spinner("考え中..."):
                response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {
                            "role": "system",
                            "content": "あなたはzenさん専用のAIアシスタントです。zenさんは39歳、倉庫業勤務、Java初心者です。親しみやすく、わかりやすく回答してください。"
                        }
                    ] + st.session_state.messages,
                    max_tokens=500,
                    temperature=0.7
                )
                
                ai_response = response.choices[0].message.content
                st.markdown(ai_response)
                
                # AI応答をセッションに追加
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": ai_response
                })
                
        except Exception as e:
            st.error(f"❌ エラーが発生しました: {e}")
            st.info("APIキーやネット接続を確認してください")

# サイドバー
with st.sidebar:
    st.header("🛠️ 機能")
    
    # チャット履歴のクリア
    if st.button("🗑️ チャット履歴をクリア"):
        st.session_state.messages = []
        st.session_state.messages.append({
            "role": "assistant",
            "content": "チャット履歴をクリアしました。新しい会話を始めましょう！"
        })
        st.experimental_rerun()
    
    # チャット履歴のダウンロード
    if len(st.session_state.messages) > 1:
        chat_history = {
            "timestamp": datetime.now().isoformat(),
            "messages": st.session_state.messages
        }
        chat_json = json.dumps(chat_history, ensure_ascii=False, indent=2)
        
        st.download_button(
            label="💾 チャット履歴をダウンロード",
            data=chat_json,
            file_name=f"zen_ai_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )
    
    st.markdown("---")
    st.markdown("**💡 使い方**")
    st.markdown("- Java学習について質問")
    st.markdown("- 業務の相談")
    st.markdown("- プログラミングのヘルプ")
    st.markdown("- その他何でも！")
    
    st.markdown("---")
    st.caption(f"zenさん専用AI v2.0 | {datetime.now().strftime('%Y-%m-%d')}")
