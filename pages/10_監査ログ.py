import pandas as pd
import streamlit as st

from core.db import (
    get_event_label,
    get_event_options,
    get_reason_label,
    init_db,
    search_audit_logs,
    summarize_audit_log_row,
)

init_db()


st.title("🧾 監査ログ")
st.write("誰が、いつ、何を、なぜ変えたかを横断で確認する最小画面です。")
st.caption("まずは閲覧専用です。")

with st.expander("検索条件", expanded=True):
    event_types = st.multiselect(
        "イベント種別",
        options=get_event_options(),
        format_func=get_event_label,
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
            "イベント": get_event_label(summary["event_type"]),
            "作業者": summary["user_id"] or "-",
            "指示ID": summary["order_id"],
            "明細ID": summary["line_id"],
            "商品コード": summary["item_code"] or "-",
            "ロケーション": summary["location_code"] or "-",
            "理由": get_reason_label(summary["reason_code"]),
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
            f"**{idx}. {get_event_label(d.get('event_type'))} / "
            f"{d.get('event_at') or '-'} / id={d.get('id')}**"
        )
        st.caption("before_value")
        st.code(d.get("before_value") or "-", language="json")
        st.caption("after_value")
        st.code(d.get("after_value") or "-", language="json")
