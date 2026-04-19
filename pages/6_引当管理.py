import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    create_order_with_lines,
    get_recent_order_lines,
    list_orders_for_ship_confirm,
    get_physical_stock_by_item,
    get_allocation_strategy,
    get_enhanced_order_lines,
    get_allocation_details_for_order,
    get_approval_label,
    get_reason_options,
    get_state_label,
    save_line_state,
    reallocate_shortage_for_line,
    log_audit_event,
    build_alloc_status,
    get_order_competition_by_item,
)

init_db()

st.title("📌 引当管理（P0最小共通基盤版）")
st.write("出荷指示を登録し、引当結果に状態・理由・承認要否・影響件数を載せます。")
st.caption(f"現在の引当戦略: {get_allocation_strategy()}")
st.info(
    "A-06状態ガイド: HOLD = 現物不足などで一旦止める / "
    "REALLOC_PENDING = 別ロケへ再引当待ち"
)

with st.expander("現在庫サマリ（商品コード合計）", expanded=False):
    phys = get_physical_stock_by_item()
    if phys:
        summary = [{"商品コード": k, "現物在庫計": v} for k, v in sorted(phys.items())]
        st.dataframe(pd.DataFrame(summary), width="stretch")
    else:
        st.info("在庫トランザクションから集計できる現物在庫はまだありません")


def parse_detail_lines(text: str):
    result = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            return None, f"カンマ区切りで入力してください: {raw}"
        left, right = line.split(",", 1)
        item = left.strip()
        if not item:
            return None, f"商品コードが空です: {raw}"
        try:
            qty = float(right.strip())
        except ValueError:
            return None, f"数量が数値ではありません: {raw}"
        if qty <= 0:
            return None, f"数量は0より大きくしてください: {raw}"
        result.append((item, qty))
    if not result:
        return None, "有効な明細行がありません（例: ITEM-001,10）"
    return result, None


def _competition_display_rows(rows):
    """get_order_competition_by_item の行を画面用の dict リストに整形する。"""
    out = []
    for r in rows:
        ref = (r.get("reference") or "").strip() or "(番号なし)"
        out.append(
            {
                "出荷指示番号": ref,
                "明細ID": int(r["line_id"]),
                "必要数": float(r["qty_required"]),
                "引当済": float(r["qty_allocated"]),
                "出荷済": float(r["shipped_qty"]),
                "未引当": float(r["qty_pending"]),
                "未出荷引当": float(r["qty_unshipped"]),
                "引当状態": r.get("alloc_status") or build_alloc_status(
                    r["qty_required"], r["qty_allocated"]
                ),
            }
        )
    return out


def show_state_save_result(ok: bool, msg: str):
    if not ok:
        st.error(msg)
    elif msg == "変更なしです":
        st.info(msg)
    else:
        st.success(msg)
        st.rerun()


def render_order_state_section(order_id: int, title: str, key_prefix: str, operator_name: str):
    st.divider()
    st.subheader(title)
    latest_rows = get_enhanced_order_lines(order_id)
    if not latest_rows:
        st.info("この出荷指示に明細がありません")
        return

    reason_labels = get_reason_options()
    df_latest = pd.DataFrame(latest_rows)
    if "state_reason" in df_latest.columns:
        df_latest["state_reason"] = df_latest["state_reason"].map(
            lambda code: reason_labels.get(code, code) if code else "-"
        )
    if "state_code" in df_latest.columns:
        df_latest["state_code"] = df_latest["state_code"].map(get_state_label)
    if "approval_status" in df_latest.columns:
        df_latest["approval_status"] = df_latest["approval_status"].map(get_approval_label)
    df_latest["引当状態"] = df_latest.apply(
        lambda r: build_alloc_status(r["qty_required"], r["qty_allocated"]),
        axis=1,
    )
    df_latest = df_latest.rename(
        columns={
            "line_id": "明細ID",
            "item_code": "商品コード",
            "qty_required": "必要数",
            "qty_allocated": "引当済数量",
            "qty_unshipped": "未出荷数量",
            "state_code": "状態コード",
            "state_label": "状態",
            "state_reason": "状態理由",
            "impact_order_count": "影響案件数",
            "approval_required": "承認要否",
            "approval_status": "承認コード",
            "approval_label": "承認状態",
            "changed_by": "更新者",
            "changed_at": "更新日時",
        }
    )
    show_cols = [
        "明細ID", "商品コード", "必要数", "引当済数量", "未出荷数量", "引当状態",
        "状態", "状態理由", "影響案件数", "承認要否", "承認状態",
        "更新者", "更新日時"
    ]
    st.dataframe(df_latest[show_cols], width="stretch")

    st.caption("必要に応じて状態だけ手動更新")
    reason_options = [""] + list(get_reason_options().keys())
    state_options = ["UNALLOCATED", "PARTIAL_ALLOCATED", "ALLOCATED", "REALLOC_PENDING", "HOLD"]
    approval_options = ["NOT_REQUIRED", "WAITING", "APPROVED", "REJECTED"]
    for row in latest_rows:
        lid = int(row["line_id"])
        with st.expander(f"明細 {lid} / {row['item_code']} の状態更新", expanded=False):
            if int(row.get("impact_order_count") or 0) > 0:
                st.warning(f"影響案件数: {int(row['impact_order_count'])}（他案件への影響あり）")

            c1, c2, c3 = st.columns(3)
            with c1:
                state_code = st.selectbox(
                    "状態",
                    options=state_options,
                    index=state_options.index(row["state_code"] if row["state_code"] in state_options else "ALLOCATED"),
                    format_func=get_state_label,
                    key=f"{key_prefix}_state_{lid}",
                )
            with c2:
                reason_options_dynamic = reason_options
                if state_code == "HOLD":
                    reason_options_dynamic = ["", "SHORTAGE"] + [
                        c for c in reason_options if c not in ("", "SHORTAGE")
                    ]
                elif state_code == "REALLOC_PENDING":
                    reason_options_dynamic = ["", "RELOCATION"] + [
                        c for c in reason_options if c not in ("", "RELOCATION")
                    ]
                reason_code = st.selectbox(
                    "理由コード",
                    options=reason_options_dynamic,
                    format_func=lambda code: reason_labels.get(code, "選択してください") if code else "選択してください",
                    key=f"{key_prefix}_reason_{lid}",
                )
            with c3:
                approval_required = st.checkbox("承認要否", value=bool(row["approval_required"]), key=f"{key_prefix}_appr_req_{lid}")

            if state_code == "HOLD":
                st.caption("HOLD推奨理由: SHORTAGE（引当ロケ不足）")
            elif state_code == "REALLOC_PENDING":
                st.caption("REALLOC_PENDING推奨理由: RELOCATION（別ロケ再配分）")

            approval_status = st.selectbox(
                "承認状態",
                options=approval_options,
                index=approval_options.index(row["approval_status"] if row["approval_status"] in approval_options else "NOT_REQUIRED"),
                format_func=get_approval_label,
                key=f"{key_prefix}_appr_status_{lid}",
            )
            if state_code == "HOLD":
                hold_flag = st.checkbox("保留", value=True, key=f"{key_prefix}_hold_{lid}")
                hold_reason = st.text_input("保留理由", value=row.get("hold_reason") or "", key=f"{key_prefix}_hold_reason_{lid}")
            else:
                hold_flag = False
                hold_reason = None
                if row.get("hold_reason"):
                    st.caption("保留解除状態で保存すると、現在状態の保留理由は空になります。")

            if st.button("状態を保存", key=f"{key_prefix}_save_state_{lid}"):
                if row["impact_order_count"] > 0 and state_code == "REALLOC_PENDING" and not reason_code:
                    st.error("他案件影響ありの再引当待ちは理由コードが必要です")
                elif approval_required and approval_status != "APPROVED":
                    st.warning("承認要のままです。承認待ちでも保存はできますが、出荷確定では停止します")
                    ok, msg = save_line_state(
                        line_id=lid,
                        state_code=state_code,
                        state_reason=reason_code or None,
                        hold_flag=hold_flag,
                        hold_reason=hold_reason or None,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        impact_order_count=row["impact_order_count"],
                        changed_by=operator_name.strip() or None,
                        free_note="引当管理画面から更新",
                    )
                    show_state_save_result(ok, msg)
                else:
                    ok, msg = save_line_state(
                        line_id=lid,
                        state_code=state_code,
                        state_reason=reason_code or None,
                        hold_flag=hold_flag,
                        hold_reason=hold_reason or None,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        impact_order_count=row["impact_order_count"],
                        changed_by=operator_name.strip() or None,
                        free_note="引当管理画面から更新",
                    )
                    show_state_save_result(ok, msg)


with st.form("alloc_order_form"):
    reference = st.text_input("出荷指示番号（参照用）", placeholder="SO-20260412-001")
    note = st.text_input("備考", placeholder="")
    detail_text = st.text_area(
        "明細（1行につき1品目。形式: 商品コード,数量）",
        height=160,
        placeholder="ITEM-001,10\nITEM-002,5",
    )
    operator = st.text_input("作業者", value="zen")
    submitted = st.form_submit_button("出荷指示を登録（引当計算）")

    if submitted:
        ref = reference.strip()
        if not ref:
            st.error("出荷指示番号を入力してください")
        else:
            lines, err = parse_detail_lines(detail_text)
            if err:
                st.error(err)
            else:
                order_id, results = create_order_with_lines(ref, note.strip() or None, lines)
                if order_id is None:
                    st.error("明細の登録に失敗しました")
                else:
                    for row in get_enhanced_order_lines(order_id):
                        state_code = row["state_code"]
                        ok, msg = save_line_state(
                            line_id=row["line_id"],
                            state_code=state_code,
                            state_reason=None,
                            hold_flag=False,
                            approval_required=False,
                            approval_status="NOT_REQUIRED",
                            impact_order_count=row["impact_order_count"],
                            changed_by=operator.strip() or None,
                            free_note="新規引当登録",
                        )
                    log_audit_event(
                        event_type="ALLOCATE",
                        user_id=operator.strip() or None,
                        order_id=order_id,
                        order_no=ref,
                        after_value=results,
                        free_note="出荷指示登録と引当計算",
                    )
                    st.success(f"出荷指示を登録しました（order_id={order_id}）")
                    st.session_state["last_alloc_order_id"] = order_id
                    st.session_state["last_alloc_item_codes"] = sorted(
                        {r["item_code"] for r in results}
                    )
                    st.session_state["last_alloc_register_snapshot"] = [
                        dict(r) for r in results
                    ]
                    st.rerun()

st.divider()
snap = st.session_state.get("last_alloc_register_snapshot")
if snap:
    st.subheader("直近登録の引当結果（数量）")
    snap_rows = []
    for r in snap:
        snap_rows.append(
            {
                "商品コード": r["item_code"],
                "必要数": float(r["qty_required"]),
                "引当済": float(r["qty_allocated"]),
                "未引当": float(r["qty_pending"]),
                "引当状態": build_alloc_status(r["qty_required"], r["qty_allocated"]),
            }
        )
    st.dataframe(pd.DataFrame(snap_rows), width="stretch")
    codes = st.session_state.get("last_alloc_item_codes") or []
    if codes:
        with st.expander("同一商品の案件競合一覧（直近登録に含まれる商品）", expanded=False):
            st.caption("同一商品について、他案件を含む全明細の引当状況です。")
            for ic in codes:
                st.markdown(f"**商品: {ic}**")
                comp = get_order_competition_by_item(ic)
                disp = _competition_display_rows(comp)
                if not disp:
                    st.info("該当する出荷明細がありません。")
                else:
                    st.dataframe(pd.DataFrame(disp), width="stretch")

st.subheader("既存出荷指示の状態更新")
order_rows = list_orders_for_ship_confirm()
if order_rows:
    order_labels = []
    order_map = {}
    for r in order_rows:
        ref = (r["reference"] or "").strip() or "(番号なし)"
        label = f"{ref} ・ 指示ID {r['order_id']}"
        order_labels.append(label)
        order_map[label] = int(r["order_id"])
    selected_order_label = st.selectbox("更新対象の出荷指示", order_labels, key="existing_order_select")
    selected_order_id = order_map[selected_order_label]
    render_order_state_section(
        order_id=selected_order_id,
        title=f"選択中 order_id={selected_order_id} の引当状態",
        key_prefix=f"existing_{selected_order_id}",
        operator_name=operator,
    )

    st.subheader("A-06 最小再引当（同一明細内）")
    selected_lines = get_enhanced_order_lines(selected_order_id)
    if selected_lines:
        line_labels = [
            f"line_id={int(r['line_id'])} / {r['item_code']} / 未出荷={float(r['qty_unshipped']):g}"
            for r in selected_lines
        ]
        line_map = {line_labels[i]: selected_lines[i] for i in range(len(selected_lines))}
        chosen_line_label = st.selectbox("再引当対象の明細", line_labels, key=f"realloc_line_{selected_order_id}")
        selected_line = line_map[chosen_line_label]
        selected_line_id = int(selected_line["line_id"])

        ad_rows = [dict(r) for r in get_allocation_details_for_order(selected_order_id)]
        line_ad_rows = [r for r in ad_rows if int(r["line_id"]) == selected_line_id]
        if line_ad_rows:
            df_line_ad = pd.DataFrame(line_ad_rows).rename(
                columns={
                    "line_id": "明細ID",
                    "item_code": "商品コード",
                    "location_code": "ロケーション",
                    "allocated_qty": "引当済数量",
                    "shipped_qty": "出荷済数量",
                    "qty_unshipped": "未出荷数量",
                }
            )
            st.dataframe(df_line_ad[["明細ID", "商品コード", "ロケーション", "引当済数量", "出荷済数量", "未出荷数量"]], width="stretch")

            from_candidates = [
                r["location_code"]
                for r in line_ad_rows
                if float(r.get("qty_unshipped") or 0.0) > 0
            ]
            if from_candidates:
                from_location = st.selectbox(
                    "再引当元ロケ",
                    options=from_candidates,
                    key=f"realloc_from_{selected_order_id}_{selected_line_id}",
                )
                from_unshipped = 0.0
                for r in line_ad_rows:
                    if r["location_code"] == from_location:
                        from_unshipped += float(r.get("qty_unshipped") or 0.0)
                to_location = st.text_input(
                    "再引当先ロケ",
                    value="",
                    placeholder="B-02-01",
                    key=f"realloc_to_{selected_order_id}_{selected_line_id}",
                )
                realloc_qty = st.number_input(
                    "再引当数量",
                    min_value=0.0,
                    max_value=float(from_unshipped),
                    value=0.0,
                    step=1.0,
                    key=f"realloc_qty_{selected_order_id}_{selected_line_id}",
                )
                if st.button("再引当を実行", key=f"do_realloc_{selected_order_id}_{selected_line_id}"):
                    ok, msg = reallocate_shortage_for_line(
                        line_id=selected_line_id,
                        from_location=from_location,
                        to_location=to_location.strip(),
                        qty=float(realloc_qty),
                        changed_by=operator.strip() or None,
                        reason_code="RELOCATION",
                    )
                    if ok:
                        save_line_state(
                            line_id=selected_line_id,
                            state_code="ALLOCATED",
                            state_reason="RELOCATION",
                            hold_flag=False,
                            hold_reason=None,
                            approval_required=False,
                            approval_status="NOT_REQUIRED",
                            impact_order_count=int(selected_line.get("impact_order_count") or 0),
                            changed_by=operator.strip() or None,
                            free_note="A-06再引当後にALLOCATEDへ復帰",
                        )
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("この明細に再引当元候補（未出荷引当ありロケ）がありません。")
        else:
            st.info("この明細にはロケーション別引当明細がありません。")
    else:
        st.info("この出荷指示には再引当対象の明細がありません。")
else:
    st.info("更新対象となる出荷指示がありません。")

last_order_id = st.session_state.get("last_alloc_order_id")
if last_order_id:
    render_order_state_section(
        order_id=int(last_order_id),
        title=f"直近登録 order_id={last_order_id} の引当状態",
        key_prefix=f"last_{last_order_id}",
        operator_name=operator,
    )

st.divider()
st.subheader("最近の引当明細")
rows = get_recent_order_lines(limit=40)
if rows:
    df_hist = pd.DataFrame([dict(row) for row in rows])
    df_hist["引当状態"] = df_hist.apply(
        lambda r: build_alloc_status(r["qty_required"], r["qty_allocated"]),
        axis=1,
    )
    df_hist = df_hist.rename(
        columns={
            "order_id": "指示ID",
            "reference": "出荷指示番号",
            "order_created": "登録日時",
            "line_id": "明細ID",
            "item_code": "商品コード",
            "qty_required": "必要数",
            "qty_allocated": "引当済数量",
            "shipped_qty": "出荷済数量",
            "qty_pending": "未引当",
            "qty_unshipped": "未出荷引当",
        }
    )
    hist_cols = [
        "指示ID",
        "出荷指示番号",
        "登録日時",
        "明細ID",
        "商品コード",
        "必要数",
        "引当済数量",
        "出荷済数量",
        "未引当",
        "未出荷引当",
        "引当状態",
    ]
    st.dataframe(df_hist[hist_cols], width="stretch")
else:
    st.info("まだ引当明細はありません")
