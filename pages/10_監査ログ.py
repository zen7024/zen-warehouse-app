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


def _display_text(value, default="-"):
    text = str(value).strip() if value is not None else ""
    return text or default


def _truncate_text(value, limit=40, default="-"):
    text = _display_text(value, default=default)
    if text == default:
        return default
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_event_at(value):
    text = _display_text(value)
    if text == "-":
        return "-"
    return text.replace("T", " ")


st.title("🧾 監査ログ")
st.write("誰が、いつ、何を、なぜ変えたかを横断で確認する最小画面です。")
st.caption("まずは閲覧専用です。")

with st.expander("検索条件", expanded=True):
    event_types = st.multiselect(
        "イベント種別で絞り込む",
        options=get_event_options(),
        format_func=get_event_label,
        default=[],
        placeholder="未選択で全イベント",
    )
    st.caption("イベント種別は未選択で全件表示です。複数選択して絞り込めます。")

    c1, c2, c3 = st.columns(3)
    with c1:
        item_code = st.text_input("商品コード", value="", placeholder="例: ITEM-001")
        user_id = st.text_input("作業者", value="", placeholder="例: zen")
    with c2:
        order_id_text = st.text_input("指示ID", value="", placeholder="例: 1001")
        reason_code = st.text_input("理由コード", value="", placeholder="例: NORMAL_SHIPMENT")
    with c3:
        keyword = st.text_input("キーワード", value="", placeholder="自由記述や JSON 内の文字列")
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

selected_events_text = " / ".join(get_event_label(code) for code in event_types) if event_types else "全イベント"
st.caption(f"表示条件: イベント種別={selected_events_text}")

display_rows = []
for row in rows:
    summary = summarize_audit_log_row(row)
    display_rows.append(
        {
            "日時": _format_event_at(summary["event_at"]),
            "イベント": get_event_label(summary["event_type"]),
            "理由": get_reason_label(summary["reason_code"]),
            "変更前": _truncate_text(summary["before_summary"], limit=48),
            "変更後": _truncate_text(summary["after_summary"], limit=48),
            "作業者": _display_text(summary["user_id"]),
            "指示ID": _display_text(summary["order_id"]),
            "明細ID": _display_text(summary["line_id"]),
            "商品コード": _display_text(summary["item_code"]),
            "ロケーション": _display_text(summary["location_code"]),
            "メモ": _truncate_text(summary["free_note"], limit=36),
        }
    )

df = pd.DataFrame(display_rows)
df = df[
    [
        "日時",
        "イベント",
        "理由",
        "変更前",
        "変更後",
        "作業者",
        "指示ID",
        "明細ID",
        "商品コード",
        "ロケーション",
        "メモ",
    ]
]
st.dataframe(df, width="stretch")
st.caption("一覧は要約を短縮表示しています。詳細は下部の JSON で確認できます。")

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
