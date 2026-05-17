# 次セッション引継ぎ: Phase 2 着手前タスク

## 状況サマリ

- **ブランチ**: `feat/inventory-transactions-foundation`
- **最新コミット**: `e30bdee`（SLH-009 / SLH-010 回帰テスト記録 Section 14 追記）
- **Phase 1 基盤**: 2026-05-17 正式完了

### Phase 1 完了済みテスト一覧

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

### Notion 更新済み（2026-05-17）

- 📦 在庫管理アプリ 概要書：Phase 1 完了・フェーズ完了ログ追記
- 🧪 テスト結果ログ：SLH-009/010 Pass・A系 Pass 更新
- ⚡ zenOS Light Context：要更新（下記 Step 0 参照）

---

## Phase 2 着手前タスク

### Step 0: zenOS Light Context を更新する

Notion の zenOS Light Context（Page ID: 3408cd0af1c881a1ac15d89f9ac95f42）を開き、
以下の内容に更新する。

**最優先タスク（修正）:**
```
- 副業起動 — Coconala / CrowdWorks 本格始動
- ITパスポート — フェーズ2（分野別インプット＋過去問道場）継続中・目標受験6月
- zen-warehouse-app Phase 2 設計着手 — Phase 1 完了済み・docs/phase2_multi_user_design.md 作成から
```

**状態メモ（修正）:**
```
KDP保留中（創作大賞結果待ち）。copipe-tool稼働中（Render + PostgreSQL）。
哲学エッセイ第57〜59章note公開済み。
zen-warehouse-app Phase 1 全テスト完了（2026-05-17）。Phase 2 設計着手待ち。
```

---

### Step 1: GitHub push 確認

最新コミット `e30bdee` が remote に push 済みか確認する。

```bash
cd /Users/zen/Projects/zen-warehouse-app
git status
git log --oneline -5
git push
```

push 済みなら次へ。未 push なら push してから次へ。

---

### Step 2: Phase 1 完了状態の固定確認

以下が整合していることを確認する（差異があれば修正する）。

| 確認対象 | 内容 |
|---|---|
| `docs/state_list_hub_regression_test_cases.md` | Section 14 が最新記録 |
| Notion「在庫管理アプリ 概要書」| Phase 1 ✅ 完了・フェーズ完了ログあり |
| Notion「テスト結果ログ」 | SLH-009/010 ✅ Pass・未解決なし |
| CLAUDE.md の検証済みシナリオ表 | A-09派生 ✅ Pass 記載あり |

CLAUDE.md の確認コマンド:

```bash
grep -A 10 "検証済みシナリオ" /Users/zen/Projects/zen-warehouse-app/CLAUDE.md
```

---

### Step 3: Phase 2 の入口整理

**Phase 2 の目標（概要書より）:**
- 多ユーザー化
- 認証の DB 管理化
- ロール設計（閲覧 / 入庫担当 / 管理者）
- SQLite → PostgreSQL / Supabase 移行準備
- Streamlit Cloud または Railway でクラウドデプロイ

**着手方針（重要）:**
いきなり DB 移行には入らない。
最初は「ユーザー・権限・倉庫切替の設計整理」から始める。

---

### Step 4: Phase 2 最初の実装候補（優先順）

1. `user / role / warehouse` の最小マスタ設計
2. 現在のハードコード認証（`streamlit-authenticator`）の棚卸し
3. 画面ごとの権限整理
4. PostgreSQL 移行前の DB 差分整理
5. QRスキャナー修正と商品登録画面の扱いを決める

---

### Step 5: 次回開始時の推奨作業（最初にやること）

**コード実装より先に、設計ドキュメントを作る。**

作成対象ファイル: `docs/phase2_multi_user_design.md`

記載内容:
- Phase 2 の目的
- ユーザー種別
- ロール一覧
- 倉庫切替の扱い
- 画面別の権限表
- SQLite 試作でできる範囲
- PostgreSQL 移行後にやる範囲

---

## 注意事項

- Phase 1 の完了状態を壊さない
- 既存の状態一覧ハブ・監査ログ・引当・出荷・解除の動作には触らない
- まず設計ドキュメント作成を優先し、コードは後から

---

## 参照ドキュメント

- `docs/state_list_hub_regression_test_cases.md` — 全テストケース定義と実施記録
- `design.md` — 設計判断・状態遷移の根拠ドキュメント
- `CLAUDE.md` — プロジェクト概要・アーキテクチャ原則
- Notion「在庫管理アプリ 概要書」— フェーズロードマップ
- Notion「テスト結果ログ」— 全テスト結果集約
