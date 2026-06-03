# Phase 2 多ユーザー化 設計メモ

作成日：2026-05-17
対象ブランチ：`feat/inventory-transactions-foundation`
Phase 1 完了コミット：`e30bdee`

---

## 1. 目的

Phase 1 では単一ユーザー前提で在庫管理の基盤（入庫〜出荷確定・引当・例外処理）を構築した。
Phase 2 では、その基盤を壊さないまま以下を追加する。

- **多ユーザー対応**：複数のオペレーターが同一システムを使える状態にする
- **ロール設計**：操作できる画面・できない画面をロール単位で制御する
- **倉庫切替**：ユーザーごとに利用可能な倉庫を管理し、画面を倉庫単位でフィルタする
- **段階的移行**：いきなり PostgreSQL に移行するのではなく、まず SQLite 試作上で設計を検証する

Phase 2 の入口は「設計を固めること」であり、コード実装はその後に行う。

---

## 2. Phase 1 完了状態

### 完了日

**2026-05-17**（Phase 1 基盤 正式完了）

### 完了したテスト

| テストID | 内容 | 判定 |
|---|---|---|
| SLH-001〜SLH-010 | 状態一覧ハブ 全10状態パターン | ✅ Pass |
| RT-001〜RT-003 | 戻り導線・回帰テスト | ✅ Pass |
| エッジケースB | 境界値 | ✅ Pass |
| A-06 | 引当ロケ現物不足 → HOLD → 再引当 → SHIPPED | ✅ Pass |
| A-09 | 出荷確定前引当解除 → 残出荷 → SHIPPED | ✅ Pass |
| A-09派生 | 一部出荷済みありで未出荷分のみ解除 | ✅ Pass |
| A-10 | 同商品複数出荷要求の競合・二重引当防止 | ✅ Pass |
| A-15 | 入荷遅延と出荷優先の同時発生 | ✅ Pass |

### 既存で壊してはいけない機能

| 機能 | 概要 |
|---|---|
| 状態一覧ハブ（`pages/11_状態一覧.py`） | 全 order_lines の状態を一覧表示し、監査・出荷・解除へ導線を持つ実務ハブ |
| 監査ログ（`pages/10_監査ログ.py`） | 全イベントを `audit_logs` テーブルに記録・表示する |
| 引当管理（`pages/6_引当管理.py`） | ロケーション別の引当操作と競合チェック |
| 引当可能在庫（`pages/7_引当可能在庫.py`） | 引当可能な在庫一覧と競合状況の表示 |
| 出荷確定（`pages/8_出荷確定.py`） | 引当済明細の出荷確定・`issue` イベント発行 |
| 引当解除（`pages/9_引当解除.py`） | 引当解除・理由コード記録・監査ログ連携 |

---

## 3. Phase 2 の基本方針

- **いきなり PostgreSQL 移行に入らない**。DB 移行はロール・倉庫設計が固まってから行う。
- **まず SQLite 試作上で設計を検証する**。仮マスタを追加し、画面フィルタと権限チェックを試作する。
- **既存の数量整合と状態履歴を壊さない**。`inventory_transactions` / `order_lines` / `allocation_details` / `audit_logs` は触らない。
- **内部コードは英語、外部表示は日本語**。`role_code` / `warehouse_code` はすべて英数字。画面ラベルは `core/db.py` で定義する。
- **試作でできることと本番向けに必要なことを分ける**。SQLite で試作できる範囲とPostgreSQL 移行後に対応する範囲を明確にしておく（→ セクション 9・10 参照）。

---

## 4. 想定ユーザー

### 主要ユーザー種別

| ユーザー種別 | 役割 | 主な操作 | できること | できないこと | 注意点 |
|---|---|---|---|---|---|
| 現場作業者 | 入庫・出庫・移動など日常的な在庫操作を担当 | 入庫登録、出庫登録、移動登録、棚卸差異入力 | 担当倉庫の在庫操作 | 引当管理・出荷確定・マスタ変更・監査ログ参照 | 誤操作時に修正できないため、操作ミス時はリーダーに依頼 |
| リーダー | 現場作業者の操作に加え、引当・出荷確定などを担当 | 引当管理、出荷確定、引当解除、状態一覧の参照 | 現場作業者の操作全般 + 引当・出荷確定・引当解除 | マスタ変更・ユーザー管理 | 引当解除の理由コード入力が必須 |
| 管理者 | 業務全体を統括し、異常対応・マスタ管理を担う | 全画面操作、監査ログの確認・エクスポート | すべての在庫操作 + 監査ログ参照 | システム設定変更・ユーザー追加 | 監査ログは参照のみ（改ざん不可） |
| 閲覧専用 | 在庫状況の参照のみ。操作は一切できない | 現在庫・状態一覧・監査ログの閲覧 | 閲覧のみ | すべての更新操作 | 倉庫フィルタは適用される |
| システム管理者 | ユーザー管理・ロール付与・倉庫マスタ管理を行う | ユーザー追加・削除、ロール付与、倉庫マスタ編集 | すべての操作 + ユーザー・マスタ管理 | なし（全権限） | 監査ログへの記録は必須 |

### 将来候補（Phase 2 スコープ外）

| 種別 | 概要 |
|---|---|
| 荷主 / 取引先 | 自社在庫の参照のみ。テナント分離（`company_id`）が前提 |
| 本社管理者 | 複数倉庫をまたぐ在庫状況の閲覧。マルチテナント設計が前提 |

---

## 5. ロール設計

### ロール一覧

| ロールコード | 表示名 | 想定利用者 | 更新可否 | 承認可否 | マスタ変更可否 |
|---|---|---|---|---|---|
| `WORKER` | 現場作業者 | ピッキング担当、入庫担当など | 〇（在庫操作のみ） | × | × |
| `LEADER` | リーダー | 班長、シフトリーダーなど | 〇（全在庫操作） | 〇（引当・出荷確定） | × |
| `MANAGER` | 管理者 | 倉庫管理者、業務管理者など | 〇 | 〇 | △（倉庫設定のみ） |
| `ADMIN` | システム管理者 | IT担当、システム運用者など | 〇 | 〇 | 〇 |
| `VIEWER` | 閲覧専用 | 経営層、棚卸監査者、外部関係者など | × | × | × |

### 補足

- ロールは複数付与可能とする設計を前提とする（`user_roles` テーブルで多対多）
- 権限の優先度：`ADMIN` > `MANAGER` > `LEADER` > `WORKER` > `VIEWER`
- 画面での権限チェックは「最も高いロール」を使う方式を試作で検証する

---

## 6. 倉庫切替設計

### 倉庫マスタの列案

| 列名 | 型 | 内容 |
|---|---|---|
| `warehouse_code` | TEXT (PK) | 内部コード（例：`WH-A`、`WH-B`） |
| `warehouse_name` | TEXT | 表示名（例：`第一倉庫`、`冷蔵倉庫`） |
| `warehouse_type` | TEXT | 倉庫種別（例：`NORMAL`、`COLD`、`HAZMAT`） |
| `is_active` | INTEGER | 有効フラグ（1=有効、0=無効） |

### 検討内容

**ログイン後の倉庫選択フロー**

- ログイン後、利用可能な倉庫が複数あれば選択画面を表示する
- 利用可能倉庫が1つのみであれば選択をスキップして自動設定する
- 選択した倉庫は `st.session_state["current_warehouse"]` に保持する

**ユーザーごとの倉庫制限**

- `user_warehouses` テーブルで「ユーザー × 倉庫」の対応を管理する
- `ADMIN` ロールは全倉庫にアクセスできる（制限なし）
- `VIEWER` も対象倉庫のみ閲覧可能とする

**画面上の倉庫表示**

- `app.py` のサイドバーまたはヘッダーに現在の倉庫名を常時表示する
- 倉庫切替は任意のタイミングで行えるようにする（ページ遷移は不要）

**既存テーブルへの `warehouse_code` 追加影響**

| テーブル | 影響 | 対応方針 |
|---|---|---|
| `inventory_transactions` | 在庫イベントに倉庫コードが必要 | 後から列追加・既存データは `WH-DEFAULT` で埋める |
| `order_lines` | 出荷先倉庫の識別に必要 | 後から列追加 |
| `allocation_details` | ロケーションが倉庫に紐づく | ロケーションに `warehouse_code` を持たせる方が自然 |
| `audit_logs` | 操作した倉庫の記録に必要 | 後から列追加 |

> 注意：既存データへの `warehouse_code` 設定は、SQLite 試作段階では `WH-DEFAULT` 一括設定とし、PostgreSQL 移行時に正式なデータ整備を行う。

---

## 7. 画面別権限表

| 画面 | WORKER | LEADER | MANAGER | ADMIN | VIEWER | 備考 |
|---|---|---|---|---|---|---|
| 入庫 | 〇 | 〇 | 〇 | 〇 | 閲覧のみ | WORKERは担当倉庫のみ |
| 現在庫 | 閲覧のみ | 閲覧のみ | 閲覧のみ | 閲覧のみ | 閲覧のみ | 全ロール閲覧可・倉庫フィルタあり |
| 出庫 | 〇 | 〇 | 〇 | 〇 | 閲覧のみ | WORKERは担当倉庫のみ |
| 移動 | 〇 | 〇 | 〇 | 〇 | × | 倉庫間移動はLEADER以上 |
| 棚卸差異 | △ | 〇 | 〇 | 〇 | × | WORKERは入力可・確定はLEADER以上 |
| 引当管理 | × | 〇 | 〇 | 〇 | 閲覧のみ | 引当操作はLEADER以上 |
| 引当可能在庫 | 閲覧のみ | 〇 | 〇 | 〇 | 閲覧のみ | 競合状況の閲覧はWORKERも可 |
| 出荷確定 | × | 〇 | 〇 | 〇 | × | 出荷確定はLEADER以上 |
| 引当解除 | × | 〇 | 〇 | 〇 | × | 解除操作はLEADER以上・理由コード必須 |
| 監査ログ | × | 閲覧のみ | 〇 | 〇 | × | MANAGERはエクスポート可 |
| 状態一覧 | 閲覧のみ | 〇 | 〇 | 〇 | 閲覧のみ | 導線ボタン（出荷・解除）はLEADER以上のみ表示 |

**凡例:**
- 〇 = 操作可
- △ = 条件付き（詳細は備考列参照）
- × = 不可
- 閲覧のみ = 表示のみ可（更新ボタン非表示）

---

## 8. 最小テーブル案

> このセクションはあくまで設計案として記載する。この時点では実装しない。

### users

```sql
CREATE TABLE users (
    user_id      TEXT PRIMARY KEY,   -- UUID または連番
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,     -- bcrypt等でハッシュ化（SQLite試作では平文も可）
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### roles

```sql
CREATE TABLE roles (
    role_code   TEXT PRIMARY KEY,    -- WORKER / LEADER / MANAGER / ADMIN / VIEWER
    role_name   TEXT NOT NULL,       -- 表示名（日本語）
    description TEXT
);
```

### user_roles

```sql
CREATE TABLE user_roles (
    user_id   TEXT NOT NULL REFERENCES users(user_id),
    role_code TEXT NOT NULL REFERENCES roles(role_code),
    PRIMARY KEY (user_id, role_code)
);
```

### warehouses

```sql
CREATE TABLE warehouses (
    warehouse_code TEXT PRIMARY KEY,   -- WH-A / WH-B 等
    warehouse_name TEXT NOT NULL,
    warehouse_type TEXT NOT NULL DEFAULT 'NORMAL',  -- NORMAL / COLD / HAZMAT 等
    is_active      INTEGER NOT NULL DEFAULT 1
);
```

### user_warehouses

```sql
CREATE TABLE user_warehouses (
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    warehouse_code TEXT NOT NULL REFERENCES warehouses(warehouse_code),
    PRIMARY KEY (user_id, warehouse_code)
);
```

---

## 9. SQLite 試作でできる範囲

| 項目 | 内容 |
|---|---|
| 仮ユーザーマスタ | `users` テーブルを SQLite に追加し、固定ユーザーを数件登録する |
| 仮ロールマスタ | `roles` / `user_roles` テーブルを追加し、ロール付与を試作する |
| 画面ごとの簡易権限チェック | `session_state` に保持したロールに基づき、ボタン表示・非表示を切り替える |
| 倉庫選択の `session_state` 保持 | ログイン後に `st.session_state["current_warehouse"]` へ倉庫コードを設定する |
| 表示上の倉庫フィルタ | 各画面のクエリに `WHERE warehouse_code = ?` を追加して倉庫別に絞る |

---

## 10. PostgreSQL / Supabase 移行後にやる範囲

| 項目 | 内容 |
|---|---|
| 外部キー厳密化 | SQLite では外部キー制約が弱いため、PostgreSQL 移行後に `REFERENCES` を正式適用する |
| `password_hash` 管理 | bcrypt / argon2 等による正式なハッシュ管理。SQLite 試作では簡易実装でよい |
| `company_id` / `tenant_id` | マルチテナント対応が必要な場合に追加。Phase 2 では未着手 |
| `warehouse_id`（UUID化） | 正式運用では `warehouse_code` を UUID に変更することも検討 |
| 権限の正式管理 | Row Level Security（RLS）等、DB レベルでの権限制御 |
| 監査ログとの完全連携 | `audit_logs` に `user_id` / `warehouse_code` を正式追加し、操作者・倉庫を記録する |
| 同時更新対策 | トランザクション分離レベルの設定、楽観的ロックの検討 |
| インデックス設計 | クエリ頻度・結合条件に応じたインデックス追加 |

---

## 11. 既存機能への影響

Phase 2 設計においても、以下の既存機能・データ構造は**変更しない**。

| 対象 | 影響方針 |
|---|---|
| `inventory_transactions`（在庫イベント正本） | 列追加（`warehouse_code`）は後工程。既存レコードには `WH-DEFAULT` を設定 |
| `order_lines.qty_allocated` / `shipped_qty` | 変更なし。数量整合ロジックはそのまま維持 |
| `allocation_details`（ロケーション別引当） | 変更なし。倉庫フィルタはロケーションの `warehouse_code` 経由で対応 |
| `order_state_logs` | 変更なし |
| `audit_logs` | `user_id` / `warehouse_code` 列の追加は後工程。既存ログには影響しない |
| 状態一覧ハブ（SLH-001〜010 Pass） | 権限チェック追加後も既存テスト結果を再確認して Pass を維持する |
| 出荷確定・引当解除の業務ルール | 変更なし。ロール制限を追加するが、処理ロジックには触れない |

---

## 12. 実装順序案

| 順序 | 内容 | 備考 |
|---|---|---|
| 1 | 設計ドキュメント作成 | **← 現在地（このファイル）** |
| 2 | `users` / `roles` / `warehouses` の設計確定 | SQLite 試作スキーマを `core/db.py` に追加 |
| 3 | 画面別権限表の確定 | 上記セクション 7 を実装に落とす |
| 4 | SQLite 試作用の最小マスタ追加 | `init_db()` に試作テーブルを追加、固定ユーザー数件を INSERT |
| 5 | `app.py` または共通部品でログインユーザー・ロール表示 | `session_state["current_user"]` / `["current_role"]` の設計 |
| 6 | 倉庫選択 UI 追加 | ログイン後の倉庫選択画面、`session_state["current_warehouse"]` 保持 |
| 7 | 主要画面に `warehouse_code` フィルタ追加 | 入庫・現在庫・状態一覧から順に対応 |
| 8 | 回帰テスト | SLH-001〜010 / RT-001〜003 / エッジケースB を再実施して Pass 確認 |

---

## 13. 未決事項

| 項目 | 内容 | 判断タイミング |
|---|---|---|
| 認証ライブラリ | `streamlit-authenticator` を継続するか、独自 `users` テーブルへ移行するか | Step 4〜5 設計時 |
| PostgreSQL 移行タイミング | SQLite 試作が安定した後か、クラウドデプロイと同時か | Phase 2 中盤 |
| 商品登録画面・QRスキャナー修正 | Phase 2 に含めるか、Phase 3 以降にするか | Step 3（権限表確定）時 |
| `company_id`（マルチテナント） | Phase 2 スコープに含めるか | Phase 2 開始前に決定する |
| 倉庫間移動の権限 | WORKER が自倉庫から他倉庫へ移動を実行できるか | Step 3（権限表確定）時 |

---

## 14. 次回の実装候補

Phase 2 実装の最初のスプリントで着手する候補。

1. **`user` / `role` / `warehouse` の最小マスタ追加**
   - `core/db.py` の `init_db()` に試作テーブルを追加する
   - 固定の仮ユーザー（ADMIN / LEADER / WORKER 各1名）を初期データとして INSERT する

2. **画面別権限チェック関数の設計**
   - `core/db.py` に `get_user_role(user_id)` / `has_permission(role_code, page_name)` を追加する
   - 関数シグネチャのみ先に決め、実装は後から行う

3. **倉庫切替の `session_state` 設計**
   - `app.py` でログイン後に `current_warehouse` を設定するフローを設計する
   - 倉庫リストは `warehouses` テーブルから取得する

4. **`app.py` のトップに現在ユーザー・ロール・倉庫を表示**
   - サイドバーに「ログインユーザー名 / ロール / 現在の倉庫」を常時表示する
   - まず固定値でも表示できる形にして、後から動的に切り替える

---

## 15. 2026-06-03 試作差分確認メモ

### 現在の試作で確認できたこと

- `core/db.py` には `users` / `roles` / `warehouses` / `user_roles` / `user_warehouses` の最小テーブル案が実装済み
- `app.py` では `current_user` / `current_role` / `current_warehouse` の `session_state` 保持とサイドバー表示が追加済み
- `pages/2_現在庫.py` と `pages/7_引当可能在庫.py` では、ログインユーザーに紐づく倉庫候補を選択できるUIが追加済み

### いま止めるべき点

- 倉庫選択UIは追加されたが、在庫集計関数側ではまだ `warehouse_code` による実データ絞り込みをしていない
- そのため現状は「倉庫を切り替えたように見えるが、集計結果は全件集計のまま」という試作段階
- この状態で引当管理・出荷確定・状態一覧ハブへ横展開すると、既存機能を壊さずに説明できる境界が曖昧になるため、本格実装は一旦止める

### 認証責務の整理

| 項目 | SQLite 試作での担当 | PostgreSQL / Supabase 移行後の担当候補 |
|---|---|---|
| ログイン認証 | `streamlit-authenticator` | Supabase Auth または正式認証基盤 |
| ユーザー識別 | `streamlit-authenticator` の `username` を起点に `users` を参照 | Auth UID と `users` の正式連携 |
| 表示名 | `users.display_name` | `users.display_name` |
| ロール判定 | `user_roles` / `roles` | 同左 |
| 倉庫所属判定 | `user_warehouses` / `warehouses` | 同左 |
| 画面権限制御 | Streamlit 画面側で制御 | 画面側 + DB / API 側の正式制御 |

### 次の安全な実装単位

1. 倉庫切替UIを増やす前に、読み取り系関数へ `warehouse_code` 引数を渡せる形を先に決める
2. `inventory_transactions` / `locations` / `allocation_details` のどこを倉庫の正本にするかを決める
3. 読み取り系2画面だけで倉庫フィルタを実データ反映し、回帰確認後に他画面へ展開する

### 2026-06-03 読み取り系の暫定実装メモ

- `現在庫` / `引当可能在庫` の取得関数は `warehouse_code=None` を受け取り、`None` のときは従来どおり全件集計とする
- SQLite 試作では `location` に `warehouse_code` を正式保持していないため、既存ロケーションは当面 `WH-001` 扱いで読む
- `WH-002` など追加倉庫は読み取りUIで選択できるが、正式なロケーション紐づけ前は在庫 0 件として表示される

---

*このドキュメントは Phase 2 着手前の設計メモです。実装が進むにつれて更新してください。*
