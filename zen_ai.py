# zen_ai.py - zenさん専用AIチャットボット（セキュア版）
import openai
import os
from dotenv import load_dotenv

# 環境変数を読み込み（.envファイルがある場合）
load_dotenv()

# APIキーを環境変数から取得
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("❌ APIキーが設定されていません")
    print("💡 以下のいずれかの方法でAPIキーを設定してください:")
    print("   1. export OPENAI_API_KEY='your-key-here'")
    print("   2. .envファイルに OPENAI_API_KEY=your-key-here を記載")
    exit(1)

# APIキーを設定
openai.api_key = OPENAI_API_KEY

def zen_ai_chat():
    print("🤖 zenさん専用AI起動！")
    print("💡 Java学習、データ分析、何でも聞いてください！")
    print("🚪 終了するには 'quit', 'exit', 'bye' のいずれかを入力")
    print("💻 強制終了は Ctrl+C でも可能")
    print("-" * 50)
    
    while True:
        try:
            # ユーザーの質問を取得
            user_input = input("zen: ").strip()
            
            # 終了判定
            if user_input.lower() in ['quit', 'exit', 'bye', 'q']:
                print("👋 また後で！頑張って！")
                print("🎉 今日もお疲れ様でした！")
                break
            
            # 空入力の場合
            if not user_input:
                print("🤔 何か質問してくださいね！")
                continue
            
            # OpenAI APIに質問を送信
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system", 
                        "content": "あなたはzenさん専用のAIアシスタントです。zenさんは39歳、倉庫業勤務、Java初心者です。親しみやすく、わかりやすく回答してください。"
                    },
                    {
                        "role": "user", 
                        "content": user_input
                    }
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            # AIの回答を表示
            ai_response = response.choices[0].message.content
            print(f"🤖 AI: {ai_response}")
            print("-" * 50)
            
        except KeyboardInterrupt:
            print("\n👋 強制終了しました！お疲れ様でした！")
            break
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}")
            print("🔧 APIキーやネット接続を確認してください")
            print("💡 Ctrl+C で強制終了できます")

# メイン実行
if __name__ == "__main__":
    zen_ai_chat()
