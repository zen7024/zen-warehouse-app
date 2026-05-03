# 次セッション引継ぎ: SLH-009 / SLH-010 テスト完了

## 状況サマリ

- **ブランチ**: `feat/inventory-transactions-foundation`
- **最新コミット**: `b0552ab`（エッジケースB確認コミット）
- **回帰テスト**: `docs/state_list_hub_regression_test_cases.md` の Section 12 に経緯あり

### 完了済み

| テストID | 状態 | 判定 |
|---|---|---|
| SLH-001〜SLH-008 | 全 Pass | 2026-04-26 / 2026-05-03 確認済み |
| RT-001〜RT-003 | 全 Pass | 2026-04-26 確認済み |
| エッジケースB | Pass | 2026-05-03 確認済み（コード設計 + 実ブラウザ） |

### 残タスク（このドキュメントの対象）

| テストID | 状態 | 理由 |
|---|---|---|
| SLH-009 | 保留 | ローカルDB に SENT_BACK 状態の明細が存在しない |
| SLH-010 | 保留 | ローカルDB に CANCELLED 状態の明細が存在しない |

---

## Step 1: Streamlit を起動する

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/streamlit run Home.py
```

DB パス: `data/warehouse.db`  
起動確認後、ブラウザで http://localhost:8501 を開く。

---

## Step 2: SLH-009 / SLH-010 テストデータを作成する

以下のスクリプトをプロジェクトルートで実行して、テストデータを直接 DB に INSERT する。

```bash
cd /Users/zen/Projects/zen-warehouse-app
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 - <<'EOF'
import sys
sys.path.insert(0, ".")
from core.db import init_db, insert_transaction, create_order_with_lines, save_line_state, log_audit_event, get_connection
from datetime import datetime

init_db()

def get_latest_line_id(order_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT line_id FROM order_lines WHERE order_id = ? ORDER BY line_id DESC LIMIT 1",
            (order_id,),
        )
        row = cur.fetchone()
        return row["line_id"] if row else None

now = datetime.now().isoformat(timespec="seconds")

# ── SLH-009: SENT_BACK（差戻し） ──────────────────────────────────────
print("=== SLH-009: SENT_BACK テストデータ作成 ===")

insert_transaction(
    tx_type="receipt",
    item_code="SLH009-ITEM-001",
    location_code="SLH009-A01",
    qty=5,
    lot_no="LOT-SLH009",
    reason="SLH-009テスト入庫",
    operator="zen",
    tx_time=now,
)
log_audit_event(
    event_type="RECEIPT",
    user_id="zen",
    item_code="SLH009-ITEM-001",
    location_code="SLH009-A01",
    after_value={"qty": 5.0, "reason": "SLH-009テスト入庫", "tx_time": now},
    free_note="SLH-009テスト入庫",
)

order_id_009, _ = create_order_with_lines(
    reference="SO-SLH009-001",
    note="SLH-009差戻し状態テスト用",
    line_items=[("SLH009-ITEM-001", 5)],
)
line_id_009 = get_latest_line_id(order_id_009)
print(f"  order_id={order_id_009}, line_id={line_id_009}")

# ALLOCATED → SENT_BACK の履歴を作る
ok, msg = save_line_state(
    line_id_009,
    "ALLOCATED",
    state_reason=None,
    changed_by="zen",
    free_note="SLH-009テスト: 初期引当済",
)
print(f"  ALLOCATED: {ok} / {msg}")

ok, msg = save_line_state(
    line_id_009,
    "SENT_BACK",
    state_reason="品質確認差戻し",
    changed_by="zen",
    free_note="SLH-009テスト: 差戻し状態",
)
print(f"  SENT_BACK: {ok} / {msg}")

log_audit_event(
    event_type="STATE_CHANGE",
    user_id="zen",
    item_code="SLH009-ITEM-001",
    order_id=order_id_009,
    line_id=line_id_009,
    before_value={"state_code": "ALLOCATED"},
    after_value={"state_code": "SENT_BACK", "state_reason": "品質確認差戻し"},
    reason_code="NORMAL_SHIPMENT",
    free_note="SLH-009テスト: 差戻し処理",
)

print(f"  → SLH-009 完了: 指示ID={order_id_009} / 明細ID={line_id_009}")

# ── SLH-010: CANCELLED（キャンセル） ─────────────────────────────────
print("=== SLH-010: CANCELLED テストデータ作成 ===")

insert_transaction(
    tx_type="receipt",
    item_code="SLH010-ITEM-001",
    location_code="SLH010-A01",
    qty=5,
    lot_no="LOT-SLH010",
    reason="SLH-010テスト入庫",
    operator="zen",
    tx_time=now,
)
log_audit_event(
    event_type="RECEIPT",
    user_id="zen",
    item_code="SLH010-ITEM-001",
    location_code="SLH010-A01",
    after_value={"qty": 5.0, "reason": "SLH-010テスト入庫", "tx_time": now},
    free_note="SLH-010テスト入庫",
)

order_id_010, _ = create_order_with_lines(
    reference="SO-SLH010-001",
    note="SLH-010キャンセル状態テスト用",
    line_items=[("SLH010-ITEM-001", 5)],
)
line_id_010 = get_latest_line_id(order_id_010)
print(f"  order_id={order_id_010}, line_id={line_id_010}")

# ALLOCATED → CANCELLED の履歴を作る
ok, msg = save_line_state(
    line_id_010,
    "ALLOCATED",
    state_reason=None,
    changed_by="zen",
    free_note="SLH-010テスト: 初期引当済",
)
print(f"  ALLOCATED: {ok} / {msg}")

ok, msg = save_line_state(
    line_id_010,
    "CANCELLED",
    state_reason="客先都合キャンセル",
    changed_by="zen",
    free_note="SLH-010テスト: キャンセル状態",
)
print(f"  CANCELLED: {ok} / {msg}")

log_audit_event(
    event_type="STATE_CHANGE",
    user_id="zen",
    item_code="SLH010-ITEM-001",
    order_id=order_id_010,
    line_id=line_id_010,
    before_value={"state_code": "ALLOCATED"},
    after_value={"state_code": "CANCELLED", "state_reason": "客先都合キャンセル"},
    reason_code="NORMAL_SHIPMENT",
    free_note="SLH-010テスト: キャンセル処理",
)

print(f"  → SLH-010 完了: 指示ID={order_id_010} / 明細ID={line_id_010}")
print("=== テストデータ作成完了 ===")
EOF
```

スクリプト出力から `order_id` と `line_id` を控えておく。

---

## Step 3: SLH-009 / SLH-010 を手動確認する

### SLH-009 / SENT_BACK / 差戻し

**事前確認**:  
状態一覧ページを開き、状態フィルタに「差戻し」が表示されることを確認する。

**操作手順**:
1. `pages/11_状態一覧.py` を開く
2. 状態フィルタで「差戻し」を選択
3. `SO-SLH009-001` / 商品コード `SLH009-ITEM-001` の明細を選択
4. 以下を確認する:

| 確認項目 | 期待値 |
|---|---|
| 案内文 | `差戻しまたはキャンセル状態です。まず監査ログを確認してください。` |
| primary ボタン | `監査ログで履歴確認` |
| secondary ボタン | なし |
| 出荷確定ボタン | 表示されない |
| 引当解除ボタン | 表示されない |
| 状態履歴 | 「引当済 → 差戻し」の流れが表示される |

5. 「監査ログで履歴確認」を押して `pages/10_監査ログ.py` へ遷移
6. 対象の指示ID / 明細ID が検索条件に引き継がれていることを確認

**判定**: Pass / Fail

---

### SLH-010 / CANCELLED / キャンセル

**事前確認**:  
状態一覧ページを開き、状態フィルタに「キャンセル」が表示されることを確認する。

**操作手順**:
1. `pages/11_状態一覧.py` を開く
2. 状態フィルタで「キャンセル」を選択
3. `SO-SLH010-001` / 商品コード `SLH010-ITEM-001` の明細を選択
4. 以下を確認する:

| 確認項目 | 期待値 |
|---|---|
| 案内文 | `差戻しまたはキャンセル状態です。まず監査ログを確認してください。` |
| primary ボタン | `監査ログで履歴確認` |
| secondary ボタン | なし |
| 出荷確定ボタン | 表示されない |
| 引当解除ボタン | 表示されない |
| 状態履歴 | 「引当済 → キャンセル」の流れが表示される |

5. 「監査ログで履歴確認」を押して `pages/10_監査ログ.py` へ遷移
6. 対象の指示ID / 明細ID が検索条件に引き継がれていることを確認

**判定**: Pass / Fail

---

## Step 4: 結果を記録する

### `docs/state_list_hub_regression_test_cases.md` に Section 13 を追加する

以下のテンプレートを使って Section 13 として末尾に追記する。

```markdown
---

## 13. 実施記録: YYYY-MM-DD SLH-009 / SLH-010 確認

- 実施日: YYYY-MM-DD
- 実施者: zen
- 実施ブランチ: feat/inventory-transactions-foundation
- 実施環境: ローカル Streamlit / SQLite（Python 3.12 / Streamlit 1.x）
- 対象コミット: （git log -1 --format="%h" で確認）

### SLH-009 / SENT_BACK / 差戻し

作成データ:
- 商品コード: SLH009-ITEM-001
- ロケーション: SLH009-A01
- 入庫数: 5
- 出荷指示番号: SO-SLH009-001
- 出荷指示数量: 5
- 状態理由: 品質確認差戻し

対象:
- 指示ID: （スクリプト出力を記録）
- 明細ID: （スクリプト出力を記録）

確認結果:
- 差戻しフィルタで対象明細を表示できた: 
- 案内文 OK / NG: 
- primary ボタン OK / NG: 
- secondary ボタンなし OK / NG: 
- 出荷確定・引当解除ボタン非表示 OK / NG: 
- 状態履歴に「引当済→差戻し」表示 OK / NG: 
- 監査ログ遷移・引き継ぎ OK / NG: 

判定:
Pass / Fail

---

### SLH-010 / CANCELLED / キャンセル

作成データ:
- 商品コード: SLH010-ITEM-001
- ロケーション: SLH010-A01
- 入庫数: 5
- 出荷指示番号: SO-SLH010-001
- 出荷指示数量: 5
- 状態理由: 客先都合キャンセル

対象:
- 指示ID: （スクリプト出力を記録）
- 明細ID: （スクリプト出力を記録）

確認結果:
- キャンセルフィルタで対象明細を表示できた: 
- 案内文 OK / NG: 
- primary ボタン OK / NG: 
- secondary ボタンなし OK / NG: 
- 出荷確定・引当解除ボタン非表示 OK / NG: 
- 状態履歴に「引当済→キャンセル」表示 OK / NG: 
- 監査ログ遷移・引き継ぎ OK / NG: 

判定:
Pass / Fail

---

### 総合判定

（SLH-009: Pass/Fail / SLH-010: Pass/Fail）
```

---

## Step 5: コミットする

```bash
cd /Users/zen/Projects/zen-warehouse-app
git add docs/state_list_hub_regression_test_cases.md
git commit -m "test: add SLH-009 SENT_BACK / SLH-010 CANCELLED regression test results"
```

全ケース Pass なら、`docs/state_list_hub_regression_test_cases.md` のセクション4の表の SLH-009 / SLH-010 列に `Pass` を記入してから commit すること。

---

## 補足: トラブルシューティング

### 「差戻し / キャンセル」が状態フィルタに表示されない場合

状態フィルタの選択肢は `get_all_line_state_rows()` の結果に存在する `state_code` に依存する。  
スクリプトが失敗している可能性があるため、以下で確認する。

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 - <<'EOF'
import sys; sys.path.insert(0, ".")
from core.db import init_db, get_connection
init_db()
with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT s.line_id, s.state_code, s.state_reason, s.changed_at
        FROM order_state_logs s
        WHERE s.state_code IN ('SENT_BACK', 'CANCELLED')
        ORDER BY s.id DESC LIMIT 10
    """)
    for r in cur.fetchall():
        print(dict(r))
EOF
```

### save_line_state が「変更なしです」を返す場合

最新ログと同じ `(state_code, state_reason, hold_flag, approval_status)` の組み合わせは重複とみなされてスキップされる。  
理由コードや free_note を変えるか、スクリプトを最初から再実行すること（同じ入庫・発注は重複するが状態ログは別 line_id で作られる）。

---

## 参照ドキュメント

- `docs/state_list_hub_regression_test_cases.md` — 全テストケース定義と実施記録
- `core/db.py:save_line_state()` (L.1723〜) — 状態保存関数
- `core/db.py:infer_line_state()` (L.1517〜) — 状態推論（order_state_logs の最新 state_code が優先）
- `pages/11_状態一覧.py:_build_line_state_rows()` (via db.py L.1585〜) — 状態表示ロジック
