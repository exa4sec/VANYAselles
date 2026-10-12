
import os
import json
import streamlit as st
import pandas as pd

from engine import (
    PLATFORMS,
    analyze_trends,
    fetch_trends,
    fetch_news,
    generate_draft,
    save_trends,
    log_performance,
    get_performance,
    get_trend_history,
)

st.set_page_config(
    page_title="Vanya Content Intelligence",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 Vanya Content Intelligence")
st.caption(
    "Trend research • AI content studio • Monetization analytics"
)

# Streamlit Cloud secrets, dengan fallback ke environment variables.
def get_config(name, default=""):
    try:
        value = st.secrets.get(name, default)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


api_key = get_config("OPENAI_API_KEY")
model = get_config("OPENAI_MODEL", "gpt-4.1-mini")

if "trends" not in st.session_state:
    st.session_state.trends = None

if "drafts" not in st.session_state:
    st.session_state.drafts = []

tab_trends, tab_studio, tab_analytics = st.tabs([
    "📡 Trend Hunter",
    "✍️ AI Content Studio",
    "📊 Analytics",
])

# =====================================
# TAB 1: TREND HUNTER
# =====================================
with tab_trends:
    st.subheader("Cari peluang konten")

    col1, col2 = st.columns([2, 1])

    with col1:
        limit = st.slider(
            "Jumlah topik tren",
            min_value=5,
            max_value=50,
            value=25,
        )

    with col2:
        st.metric(
            "AI API",
            "Aktif" if api_key else "Template mode",
        )

    if st.button(
        "🚀 Ambil tren terbaru",
        type="primary",
        use_container_width=True,
    ):
        try:
            with st.spinner("Mengambil dan menganalisis tren..."):
                raw = fetch_trends(limit=limit)
                df = analyze_trends(raw)
                save_trends(df)
                st.session_state.trends = df

            st.success(f"{len(df)} topik berhasil diproses.")

        except Exception as error:
            st.error(f"Gagal mengambil tren: {error}")

    df = st.session_state.trends

    if df is not None and not df.empty:
        st.info(
            "Skor adalah prioritas relatif dari data saat ini, "
            "bukan prediksi viral atau jaminan pendapatan."
        )

        display_columns = [
            "topic",
            "traffic",
            "news_count",
            "opportunity_score",
        ]

        st.dataframe(
            df[display_columns],
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "⬇️ Download data tren CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="vanya_trends.csv",
            mime="text/csv",
        )

        selected_topic = st.selectbox(
            "Pilih topik untuk dibuatkan konten",
            options=df["topic"].tolist(),
        )

        if st.button("Gunakan topik di AI Studio"):
            st.session_state.selected_topic = selected_topic
            st.success(
                "Topik dipilih. Buka tab AI Content Studio."
            )


# =====================================
# TAB 2: AI CONTENT STUDIO
# =====================================
with tab_studio:
    st.subheader("Buat draft multi-platform")

    trend_df = st.session_state.trends

    if trend_df is not None and not trend_df.empty:
        trend_options = trend_df["topic"].tolist()
    else:
        trend_options = []

    default_topic = st.session_state.get(
        "selected_topic",
        trend_options[0] if trend_options else "",
    )

    topic = st.text_input(
        "Topik",
        value=default_topic,
        placeholder="Contoh: perkembangan AI",
    )

    niche = st.text_input(
        "Niche / target audiens",
        value="Semua niche trending",
    )

    platforms = st.multiselect(
        "Platform tujuan",
        options=PLATFORMS,
        default=["TikTok", "Instagram Reels", "YouTube Shorts"],
    )

    if st.button(
        "✨ Generate draft",
        type="primary",
        use_container_width=True,
    ):
        if not topic.strip():
            st.warning("Masukkan topik terlebih dahulu.")
        elif not platforms:
            st.warning("Pilih minimal satu platform.")
        else:
            drafts = []

            try:
                with st.spinner("Vanya sedang membuat konten..."):
                    news = fetch_news(topic.strip())

                    for platform in platforms:
                        draft = generate_draft(
                            topic=topic.strip(),
                            platform=platform,
                            niche=niche,
                            news=news,
                            api_key=api_key,
                            model=model,
                        )

                        drafts.append({
                            "topic": topic.strip(),
                            "platform": platform,
                            **draft,
                        })

                st.session_state.drafts = drafts
                st.success(f"{len(drafts)} draft berhasil dibuat.")

            except Exception as error:
                st.error(f"Gagal membuat draft: {error}")

    for index, draft in enumerate(
        st.session_state.drafts
    ):
        with st.expander(
            f"{draft['platform']} • {draft['topic']}",
            expanded=(index == 0),
        ):
            st.markdown("**Angle**")
            st.write(draft["angle"])

            st.markdown("**Hook**")
            st.write(draft["hook"])

            st.markdown("**Script**")
            st.text_area(
                "Edit script",
                value=draft["script"],
                key=f"script_{index}",
                height=220,
            )

            st.markdown("**Caption**")
            st.text_area(
                "Edit caption",
                value=draft["caption"],
                key=f"caption_{index}",
                height=120,
            )

            st.markdown("**CTA**")
            st.write(draft["cta"])

            st.markdown("**Ide monetisasi**")
            st.write(draft["monetization"])

            st.warning(
                "Verifikasi fakta dan hak penggunaan materi sebelum "
                "publikasi."
            )
            st.caption(draft["verification"])

            st.download_button(
                "Download draft ini",
                data=json.dumps(
                    draft,
                    ensure_ascii=False,
                    indent=2,
                ),
                file_name=f"vanya_draft_{index + 1}.json",
                mime="application/json",
                key=f"download_{index}",
            )

    if st.session_state.drafts:
        st.download_button(
            "⬇️ Download semua draft JSON",
            data=json.dumps(
                st.session_state.drafts,
                ensure_ascii=False,
                indent=2,
            ),
            file_name="vanya_all_drafts.json",
            mime="application/json",
        )


# =====================================
# TAB 3: ANALYTICS
# =====================================
with tab_analytics:
    st.subheader("Pantau performa konten")

    with st.form("performance_form"):
        p_topic = st.text_input("Topik konten")
        p_platform = st.selectbox(
            "Platform",
            options=PLATFORMS,
        )
        p_url = st.text_input("URL posting, opsional")

        c1, c2, c3 = st.columns(3)

        with c1:
            views = st.number_input(
                "Views", min_value=0, step=100
            )
            likes = st.number_input(
                "Likes", min_value=0, step=10
            )

        with c2:
            comments = st.number_input(
                "Comments", min_value=0, step=1
            )
            shares = st.number_input(
                "Shares", min_value=0, step=1
            )

        with c3:
            followers = st.number_input(
                "Followers baru", min_value=0, step=1
            )
            revenue = st.number_input(
                "Pendapatan (IDR)",
                min_value=0.0,
                step=1000.0,
            )

        submitted = st.form_submit_button(
            "Simpan performa",
            type="primary",
        )

        if submitted:
            if not p_topic.strip():
                st.warning("Topik harus diisi.")
            else:
                log_performance(
                    topic=p_topic.strip(),
                    platform=p_platform,
                    views=int(views),
                    likes=int(likes),
                    comments=int(comments),
                    shares=int(shares),
                    followers=int(followers),
                    revenue=float(revenue),
                    post_url=p_url.strip(),
                )
                st.success("Performa berhasil disimpan.")

    performance = get_performance()

    if not performance.empty:
        st.divider()

        total_views = int(performance["views"].sum())
        total_revenue = float(performance["revenue"].sum())
        total_followers = int(performance["followers"].sum())

        m1, m2, m3 = st.columns(3)

        m1.metric("Total views", f"{total_views:,}")
        m2.metric("Total followers", f"{total_followers:,}")
        m3.metric(
            "Pendapatan tercatat",
            f"Rp {total_revenue:,.0f}",
        )

        performance["engagement_rate"] = (
            (
                performance["likes"]
                + performance["comments"]
                + performance["shares"]
            )
            / performance["views"].replace(0, pd.NA)
            * 100
        ).fillna(0).round(2)

        st.dataframe(
            performance,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "⬇️ Download laporan performa CSV",
            data=performance.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name="vanya_performance.csv",
            mime="text/csv",
        )

    history = get_trend_history()

    if not history.empty:
        st.divider()
        st.subheader("Histori hasil trend hunting")
        st.dataframe(
            history.head(100),
            use_container_width=True,
            hide_index=True,
        )
