import streamlit as st
import pandas as pd
from core.db import (
    init_db,
    create_order_with_lines,
    get_recent_order_lines,
    get_physical_stock_by_item,
    get_allocation_strategy,
)

init_db()

st.title("📌 引当管理（最小版）")
st.write(
    "出荷指示を1件登録し、商品ごとに現在庫と比較して引当数量・未引当を記録します。"
)
st.caption(f"現在の引当戦略: {get_allocation_strategy()}")

with st.expander("現在庫サマリ（商品コード合計）", expanded=False):
    phys = get_physical_stock_by_item()
    if phys:
        summary = [
            {"商品コード": k, "現物在庫計": v}
            for k, v in sorted(phys.items())
        ]
        st.dataframe(pd.DataFrame(summary), width="stretch")
    else:
        st.info("在庫トランザクションから集計できる現物在庫はまだありません")


def parse_detail_lines(text: str):
    """1行あたり: 商品コード,数量"""
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


with st.form("alloc_order_form"):
    reference = st.text_input("出荷指示番号（参照用）", placeholder="SO-20260412-001")
    note = st.text_input("備考", placeholder="")
    detail_text = st.text_area(
        "明細（1行につき1品目。形式: 商品コード,数量）",
        height=160,
        placeholder="ITEM-001,10\nITEM-002,5",
    )
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
                order_id, results = create_order_with_lines(
                    ref, note.strip() or None, lines
                )
                if order_id is None:
                    st.error("明細の登録に失敗しました")
                else:
                    st.success(f"出荷指示を登録しました（order_id={order_id}）")
                    df = pd.DataFrame(
                        [
                            {k: v for k, v in r.items() if k != "allocations"}
                            for r in results
                        ]
                    )
                    df = df.rename(
                        columns={
                            "item_code": "商品コード",
                            "qty_required": "必要数",
                            "qty_allocated": "引当済",
                            "qty_pending": "未引当",
                        }
                    )
                    st.dataframe(df, width="stretch")
                    alloc_rows = []
                    for r in results:
                        for a in r.get("allocations") or []:
                            alloc_rows.append(
                                {
                                    "商品コード": r["item_code"],
                                    "ロケーション": a["location_code"],
                                    "引当数量": a["qty"],
                                }
                            )
                    if alloc_rows:
                        st.caption("ロケーション別引当内訳（出荷確定時はこのロケーションから出庫されます）")
                        st.dataframe(
                            pd.DataFrame(alloc_rows),
                            width="stretch",
                        )
                    st.rerun()

st.divider()

st.subheader("最近の引当明細")

rows = get_recent_order_lines(limit=40)

if rows:
    df_hist = pd.DataFrame([dict(row) for row in rows])
    df_hist = df_hist.rename(
        columns={
            "order_id": "指示ID",
            "reference": "出荷指示番号",
            "order_created": "登録日時",
            "line_id": "明細ID",
            "item_code": "商品コード",
            "qty_required": "必要数",
            "qty_allocated": "引当済",
            "qty_pending": "未引当",
        }
    )
    st.dataframe(df_hist, width="stretch")
else:
    st.info("まだ引当明細はありません")
