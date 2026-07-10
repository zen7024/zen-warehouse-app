# CLAUDE.md — zen-warehouse-app

## プロジェクト概要

**倉庫管理アプリ（WMS）**。入庫〜出荷確定・引当管理・例外処理を一貫して扱う。

- **Tech**: Python / Streamlit / SQLite
- **GitHub**: https://github.com/zen7024/zen-warehouse-app
- **Active branch**: `feat/inventory-transactions-foundation`
- **起動コマンド**: `streamlit run app.py`

---

## ファイル構成

```
zen-warehouse-app/
├── app.py                  # メインハブ（状態サマリ表示）
├── core/
│   └── db.py               # 全DB関数・共通ラベル定義（ここが中心）
├── pages/
│   ├── 1_入庫.py
│   ├── 2_現在庫.py
│   ├── 3_出庫.py
│   ├── 4_移動.py
│   ├── 5_棚卸差異.py
│   ├── 6_引当管理.py
│   ├── 7_引当可能在庫.py
│   ├── 8_出荷確定.py
│   ├── 9_引当解除.py
│   ├── 10_監査ログ.py
│   ├── 11_状態一覧.py      # 実務ハブ（監査・出荷・解除への導線あり）
│   └── 12_商品登録.py      # 商品マスタ登録・一覧・有効/無効切替
├── design.md               # 設計判断・状態遷移の根拠ドキュメント
└── CLAUDE.md               # このファイル
```

---

## アーキテクチャ原則（必読）

### 1. イベントソース原則
- **`inventory_transactions` が在庫事実の正本**
- 物理在庫は集計で算出する。直接UPDATE禁止
- 入庫=`receipt` / 出庫=`issue` / 移動=`move` / 棚卸差異=`count_diff`

### 2. 引当の分離
- **論理引当**（`order_lines` / `allocation_details`）と**物理在庫**は完全分離
- `allocation_details` = 「どのロケーションから何を引き当てたか」の記録
- 出荷確定時に実ロケーションへ `issue` を発行する（在庫から実際に減らす）

### 3. 共通ロジックは `core/db.py` に集約
- ラベル定義: `EVENT_LABELS` / `REASON_LABELS`
- 関数: `get_event_label()` / `get_reason_label()` / `get_event_options()`
- 競合チェック: `build_alloc_status()` / `get_order_competition_by_item()`
- 状態取得: `get_all_line_state_rows()` / `get_line_state_summary()` / `get_line_state_history()`
- **画面ファイルにロジックを書かない。`core/db.py` に追加する**

### 4. 状態遷移コード（state_code）
```
ALLOCATED           → 全量引当済み
PARTIAL_ALLOCATED   → 一部引当済み
PARTIAL_SHIPPED     → 一部出荷済み（出荷済みは消えない）
SHIPPED             → 全量出荷確定
RELEASED            → 引当解除済み
HOLD                → 保留中
REALLOC_PENDING     → 再引当待ち
```

### 5. 引当解除の業務ルール
- 引当全解除 ≠ キャンセル・差戻し（別業務判断）
- 引当解除後の標準状態 = `RELEASED`
- 出荷済数量がある明細 → `PARTIAL_SHIPPED` を保持する（`PARTIAL_ALLOCATED` に下げない）
- 解除理由コード: `CUSTOMER_CHANGE` / `PRIORITY_REALLOC` / `WRONG_ALLOC` / `STOCK_DIFF` / `OTHER`
- `OTHER` のみ自由記述欄が必須

---

## コーディング規約

### 必須ルール
1. **全ページファイルの冒頭で `init_db()` を呼ぶ**（忘れると他ページでDB未初期化になる）
2. **`SELECT *` 禁止**。`ALTER TABLE` 後に列ズレが起きるため、列名を明示する
3. **ラベルは `core/db.py` の定数から取得する**。画面ファイルに日本語ラベルを直書きしない

### Streamlit セッション管理
- 画面間の遷移コンテキストは `st.session_state["detail_target"]` で共有
- `detail_target` の形式:
  ```python
  {
      "source_page": str,
      "target_page": str,
      "order_id": str,
      "line_id": int,
      "item_code": str,
      "state_code": str,
  }
  ```
- **ボタン押下前に `session_state.pop()` をしない**（RT-002 既知バグ）
  - 成功メッセージの `session_state` は「画面遷移後」にクリアする

### 監査ログ
- 全イベントを `audit_logs` に記録する
- `event_type`: `RECEIPT` / `ISSUE` / `MOVE` / `COUNT_DIFF` / `RELEASE`
- 引当解除時: `reason_code` / `free_note` / `operator` / 解除前後数量を必ず記録する

---

## 検証済みシナリオ（回帰テスト）

| シナリオ | 内容 | 状態 |
|---------|------|------|
| A-06 | 引当ロケ現物不足 → HOLD → 再引当 → SHIPPED | ✅ Pass |
| A-09 | 出荷確定前引当解除 → PARTIAL_ALLOCATED → 残出荷 → SHIPPED | ✅ Pass |
| A-09派生 | 一部出荷済みありで未出荷分のみ解除 | ✅ Pass |
| A-10 | 同商品複数出荷要求の競合・二重引当防止 | ✅ Pass |
| A-15 | 入荷遅延と出荷優先の同時発生 | ✅ Pass |

---

## 既知の注意事項

- `localhost` でStreamlitを開く際は**Chromeの自動翻訳をOFF**にする
  （翻訳がDOMを書き換えて `removeChild` エラーが発生する）
- Coworkから外部PostgreSQLへの接続は不可。DBはローカルから操作する
- Render Free PostgreSQLは有効期限あり（将来の移行要検討）

---

## 未実装・残課題（known gaps）

- 正式承認フロー
- 優先度挿入の自動化
- 入荷遅延・到着日データ管理
- マルチ理由コード（複数理由同時選択）
- 状態一覧から詳細画面への導線改善（HOLD系→監査ログ優先 / PARTIAL_SHIPPED系→出荷確定優先）
- 共通UIヘルパー関数化（競合一覧整形ロジックが pages/6・7・9 に重複）

---

## zenOS 開発方針

- **70%完成で前進**。完璧より動くものを優先する
- シナリオベースで検証する（A-XX 形式の手順書で確認）
- 大きな変更の前に `design.md` を確認・更新する
- 機能追加後は必ずコミットしてからテストを始める

---

## Notion 連携

### セッション開始時（必須）
グローバルCLAUDE.mdのLight Context fetchに加え、作業開始前に必ず以下もfetchする：

📦 在庫管理アプリ 概要書
https://www.notion.so/3348cd0af1c881f2af7bc2b4e6569507

### 読む専用・書き込みはzenOSへ
このプロジェクト内でのNotionへの書き込みは行わない。
更新依頼はzenOSプロジェクト（claude.ai）に渡す。

### キリのいいところでの更新提案
以下のタイミングで、Notion更新用の依頼文を自動生成して提案する：
- 機能の実装・動作確認が完了したとき
- フェーズの節目を通過したとき
- 「ありがとう」「今日はここまで」などセッション終了を示唆したとき

提案フォーマット（そのままzenOSにコピペできる形で出す）：
```
📋 zenOSへのNotion更新依頼

・在庫管理アプリ 概要書に追記：[変更内容・コミットID・確認結果]
・Light Contextに反映：[優先タスク変更があれば、なければ「なし」]
・portfolioに反映：[完成・公開があれば、なければ「なし」]
```

### コンテキスト警戒
以下の兆候が出始めたら即座に警告する：
- セッション序盤に読んだ内容が曖昧になっている
- 同じ確認を繰り返している
- 返答の前提が揺らいでいる

警告フォーマット：
⚠️ コンテキストが長くなっています。新しいチャットに移る前にNotion更新依頼文を作成しますか？
