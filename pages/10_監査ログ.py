import pandas as pd
import streamlit as st

from core.db import (
    get_reason_options,
    init_db,
    search_audit_logs,
    summarize_audit_log_row,
)

init_db()

EVENT_LABELS = {
    "SHIP_CONFIRM": "出荷確定",
    "RELEASE": "引当解除",
    "A06_HOLD": "A-06保留",
    "MOVE": "移動",
    "RECEIPT": "入庫",
    "ISSUE": "出庫",
    "COUNT_DIFF": "棚卸差異",
    "REALLOCATE": "再引当",
    "VIEW_ALLOCATABLE_STOCK": "引当可能在庫閲覧",
}

EVENT_OPTIONS = list(EVENT_LABELS.keys())

EXTRA_REASON_LABELS = {
    "PRIORITY_REALLOC": "優先案件へ再配分",
    "WRONG_ALLOC": "誤引当",
    "STOCK_DIFF": "在庫差異",
}


def _label_event(code):
    return EVENT_LABELS.get(code, code or "-")


def _label_reason(code, reason_labels):
    return reason_labels.get(code, EXTRA_REASON_LABELS.get(code, code or "-"))


st.title("🧾 監査ログ")
st.write("誰が、いつ、何を、なぜ変えたかを横断で確認する最小画面です。")
st.caption("まずは閲覧専用です。")

reason_labels = get_reason_options()

with st.expander("検索条件", expanded=True):
    event_types = st.multiselect(
        "イベント種別",
        options=EVENT_OPTIONS,
        format_func=_label_event,
        default=[],
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        item_code = st.text_input("商品コード", value="")
        user_id = st.text_input("作業者", value="")
    with c2:
        order_id_text = st.text_input("指示ID", value="")
        reason_code = st.text_input("理由コード", value="")
    with c3:
        keyword = st.text_input("キーワード", value="")
        limit = st.number_input("取得件数", min_value=1, max_value=500, value=100, step=10)

order_id = None
if order_id_text.strip():
    try:
        order_id = int(order_id_text.strip())
    except ValueError:
        st.error("指示IDは整数で入力してください。")
        st.stop()

rows = search_audit_logs(
    event_types=event_types or None,
    item_code=item_code.strip() or None,
    order_id=order_id,
    user_id=user_id.strip() or None,
    reason_code=reason_code.strip() or None,
    keyword=keyword.strip() or None,
    limit=int(limit),
)

st.metric("取得件数", len(rows))

if not rows:
    st.info("該当する監査ログはありません。")
    st.stop()

display_rows = []
for row in rows:
    summary = summarize_audit_log_row(row)
    display_rows.append(
        {
            "日時": summary["event_at"],
            "イベント": _label_event(summary["event_type"]),
            "作業者": summary["user_id"] or "-",
            "指示ID": summary["order_id"],
            "明細ID": summary["line_id"],
            "商品コード": summary["item_code"] or "-",
            "ロケーション": summary["location_code"] or "-",
            "理由": _label_reason(summary["reason_code"], reason_labels),
            "自由記述": summary["free_note"] or "",
            "変更前要約": summary["before_summary"],
            "変更後要約": summary["after_summary"],
        }
    )

df = pd.DataFrame(display_rows)
st.dataframe(df, width="stretch")

with st.expander("イベント別件数", expanded=False):
    count_df = (
        df["イベント"]
        .value_counts()
        .rename_axis("イベント")
        .reset_index(name="件数")
    )
    st.dataframe(count_df, width="stretch")

with st.expander("先頭20件の詳細JSON", expanded=False):
    for idx, row in enumerate(rows[:20], start=1):
        d = dict(row)
        st.markdown(
            f"**{idx}. {_label_event(d.get('event_type'))} / "
            f"{d.get('event_at') or '-'} / id={d.get('id')}**"
        )
        st.caption("before_value")
        st.code(d.get("before_value") or "-", language="json")
        st.caption("after_value")
        st.code(d.get("after_value") or "-", language="json")
