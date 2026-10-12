
from __future__ import annotations

import re
import html
from urllib.parse import (
    quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode
)

import feedparser
import pandas as pd
import requests
import streamlit as st


# ============================================================
# VANYA PRODUCT RESEARCH ENGINE
# Version 0.1 | No persistent database
# ============================================================

APP_NAME = "Vanya Product Research Engine"

REGIONS = {
    "Global": ("US", "en"),
    "United States": ("US", "en"),
    "United Kingdom": ("GB", "en"),
    "Canada": ("CA", "en"),
    "Australia": ("AU", "en"),
    "Indonesia": ("ID", "id"),
    "Germany": ("DE", "de"),
    "India": ("IN", "en"),
}

PAIN_TERMS = [
    "problem", "problems", "issue", "issues",
    "frustrating", "frustrated", "annoying",
    "difficult", "struggle", "pain point",
    "wish there was", "need a", "need an",
    "looking for", "alternative", "replacement",
    "too expensive", "doesn't work", "does not work",
]

DEMAND_TERMS = [
    "best", "recommend", "buy", "bought",
    "purchase", "review", "popular", "alternative",
    "looking for", "need a", "need an",
    "price", "compare", "versus",
]

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "fbclid", "gclid",
}


# ============================================================
# DATA CLEANING
# ============================================================

def clean_text(value) -> str:
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""

    try:
        parts = urlsplit(url.strip())

        query = [
            (key, value)
            for key, value in parse_qsl(
                parts.query, keep_blank_values=True
            )
            if key.lower() not in TRACKING_PARAMS
        ]

        return urlunsplit((
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(query, doseq=True),
            "",
        ))

    except Exception:
        return url.strip()


def classify_signal(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()

    has_pain = any(term in text for term in PAIN_TERMS)
    has_demand = any(term in text for term in DEMAND_TERMS)

    if has_pain:
        return "Keluhan"
    if has_demand:
        return "Petunjuk permintaan"

    return "Umum"


def calculate_signal_score(title: str, summary: str) -> int:
    """
    Keyword triage only.
    This is NOT a sales, demand, or opportunity score.
    """
    title = (title or "").lower()
    summary = (summary or "").lower()

    score = 0

    for term in PAIN_TERMS:
        if term in title:
            score += 3
        elif term in summary:
            score += 1

    for term in DEMAND_TERMS:
        if term in title:
            score += 2
        elif term in summary:
            score += 1

    return min(score, 100)


def make_record(
    source: str,
    title: str,
    url: str,
    published: str = "",
    summary: str = "",
) -> dict:
    title = clean_text(title)
    summary = clean_text(summary)

    return {
        "source": source,
        "title": title,
        "url": url,
        "normalized_url": normalize_url(url),
        "published": published or "",
        "signal_type": classify_signal(title, summary),
        "signal_score": calculate_signal_score(title, summary),
        "summary": summary[:1200],
    }


# ============================================================
# SOURCE 1: GOOGLE NEWS RSS
# ============================================================

def search_google_news(
    query: str,
    region: str = "Global",
    limit: int = 10,
) -> dict:
    country, language = REGIONS.get(region, ("US", "en"))

    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}"
        f"&hl={language}&gl={country}"
        f"&ceid={country}:{language}"
    )

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "VanyaResearch/0.1"},
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        records = []

        for entry in feed.entries[:limit]:
            records.append(make_record(
                source="Google News",
                title=getattr(entry, "title", ""),
                url=getattr(entry, "link", ""),
                published=getattr(entry, "published", ""),
                summary=getattr(entry, "summary", ""),
            ))

        return {"records": records, "errors": []}

    except Exception as exc:
        return {
            "records": [],
            "errors": [f"Google News gagal: {exc}"],
        }


# ============================================================
# SOURCE 2: HACKER NEWS SEARCH API
# ============================================================

def search_hacker_news(
    query: str,
    limit: int = 10,
) -> dict:
    api_url = "https://hn.algolia.com/api/v1/search"

    try:
        response = requests.get(
            api_url,
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": limit,
            },
            timeout=20,
        )
        response.raise_for_status()

        records = []

        for item in response.json().get("hits", []):
            object_id = item.get("objectID", "")

            # If a story links to an external website, preserve that URL.
            # Otherwise link to the Hacker News discussion.
            url = item.get("url") or (
                f"https://news.ycombinator.com/item?id={object_id}"
                if object_id else ""
            )

            records.append(make_record(
                source="Hacker News",
                title=item.get("title", ""),
                url=url,
                published=item.get("created_at", ""),
                summary=item.get("story_text") or "",
            ))

        return {"records": records, "errors": []}

    except Exception as exc:
        return {
            "records": [],
            "errors": [f"Hacker News gagal: {exc}"],
        }


# ============================================================
# OPTIONAL SOURCE 3: EBAY BROWSE API
# Credentials must be configured separately.
# ============================================================

def search_ebay(
    query: str,
    limit: int = 10,
) -> dict:
    import os

    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return {
            "records": [],
            "errors": [
                "eBay dilewati: EBAY_CLIENT_ID dan "
                "EBAY_CLIENT_SECRET belum dikonfigurasi."
            ],
        }

    token_url = (
        "https://api.ebay.com/identity/v1/oauth2/token"
    )
    search_url = (
        "https://api.ebay.com/buy/browse/v1/item_summary/search"
    )

    try:
        token_response = requests.post(
            token_url,
            auth=(client_id, client_secret),
            headers={
                "Content-Type":
                    "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=20,
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]

        response = requests.get(
            search_url,
            params={
                "q": query,
                "limit": min(max(limit, 1), 50),
            },
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            timeout=20,
        )
        response.raise_for_status()

        records = []

        for item in response.json().get("itemSummaries", []):
            price = item.get("price", {})
            seller = item.get("seller", {}).get("username", "")

            price_text = ""
            if price:
                price_text = (
                    f"Price: {price.get('value', '')} "
                    f"{price.get('currency', '')}"
                ).strip()

            summary = " | ".join(
                part for part in [
                    item.get("condition", ""),
                    f"Seller: {seller}" if seller else "",
                    price_text,
                ]
                if part
            )

            records.append(make_record(
                source="eBay listing",
                title=item.get("title", ""),
                url=item.get("itemWebUrl", ""),
                summary=summary,
            ))

        return {"records": records, "errors": []}

    except Exception as exc:
        return {
            "records": [],
            "errors": [f"eBay API gagal: {exc}"],
        }


# ============================================================
# GOOGLE TRENDS CSV ANALYSIS
# ============================================================

def analyze_trends_csv(file_obj):
    df = pd.read_csv(file_obj)

    if df.empty or len(df.columns) < 2:
        raise ValueError(
            "CSV harus memiliki kolom tanggal dan indeks minat."
        )

    df = df.rename(columns={
        df.columns[0]: "date",
        df.columns[1]: "interest",
    })

    df["interest"] = pd.to_numeric(
        df["interest"], errors="coerce"
    )
    df = df.dropna(subset=["interest"]).copy()

    if df.empty:
        raise ValueError(
            "Tidak ditemukan nilai indeks numerik."
        )

    first = float(df["interest"].iloc[0])
    last = float(df["interest"].iloc[-1])

    if first != 0:
        percentage = (last - first) / first * 100
        change_text = f"{percentage:+.1f}%"
    else:
        change_text = "Tidak dihitung karena nilai awal nol"

    note = (
        f"Indeks awal: {first:g} | "
        f"Indeks akhir: {last:g} | "
        f"Perubahan absolut: {last - first:+.1f} | "
        f"Perubahan relatif: {change_text}. "
        "Indeks Trends bukan volume pencarian absolut."
    )

    df["date"] = df["date"].astype(str)

    return df[["date", "interest"]], note


# ============================================================
# RESEARCH PIPELINE
# ============================================================

def run_research(
    query: str,
    region: str,
    limit: int,
    use_news: bool,
    use_hn: bool,
    use_ebay: bool,
) -> dict:
    records = []
    errors = []

    sources = []

    if use_news:
        sources.append(
            lambda: search_google_news(query, region, limit)
        )

    if use_hn:
        sources.append(
            lambda: search_hacker_news(query, limit)
        )

    if use_ebay:
        sources.append(
            lambda: search_ebay(query, limit)
        )

    for search_function in sources:
        result = search_function()
        records.extend(result["records"])
        errors.extend(result["errors"])

    if not records:
        return {"records": [], "errors": errors}

    df = pd.DataFrame(records)

    # Deduplicate by normalized URL, retaining the first occurrence.
    df = df.drop_duplicates(
        subset=["normalized_url"], keep="first"
    )

    # Empty URLs cannot establish identity, so preserve each such record.
    # They are rare, but we do not want to merge all empty URLs together.
    no_url = df["normalized_url"].eq("")
    if no_url.any():
        url_rows = df[~no_url]
        empty_url_rows = pd.DataFrame(records)
        empty_url_rows = empty_url_rows[
            empty_url_rows["normalized_url"].eq("")
        ]
        df = pd.concat(
            [url_rows, empty_url_rows], ignore_index=True
        )

    df = df.sort_values(
        ["signal_score", "source"],
        ascending=[False, True],
    )

    return {
        "records": df.to_dict("records"),
        "errors": errors,
    }


# ============================================================
# REPORTING
# ============================================================

def build_summary(df: pd.DataFrame) -> str:
    if df.empty:
        return "Belum ada data yang bisa diringkas."

    pain_count = int(
        (df["signal_type"] == "Keluhan").sum()
    )
    demand_count = int(
        (df["signal_type"] == "Petunjuk permintaan").sum()
    )

    source_counts = df["source"].value_counts().to_dict()

    sources_text = ", ".join(
        f"{name}: {count}"
        for name, count in source_counts.items()
    )

    return f"""
**Hasil pencarian**
- Hasil unik: {len(df)}
- Sinyal keluhan berbasis kata kunci: {pain_count}
- Petunjuk permintaan berbasis kata kunci: {demand_count}
- Sumber: {sources_text}

**Yang bisa disimpulkan:** hasil ini membantu menemukan topik untuk diselidiki.

**Yang belum bisa disimpulkan:** volume penjualan, jumlah penjual unik,
permintaan pasar secara absolut, profitabilitas, atau peluang bisnis
yang sudah tervalidasi.

Klasifikasi memakai kata kunci sederhana, bukan pemahaman semantik.
Buka sumber aslinya sebelum mengambil keputusan.
"""


# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🌍",
    layout="wide",
)

st.title("🌍 Vanya Product Research Engine")
st.caption(
    "Mencari sinyal permintaan dan celah pasar dari sumber publik."
)

st.info(
    "Ini MVP riset, bukan mesin prediksi penjualan. "
    "Vanya tidak menganggap listing sebagai penjualan atau "
    "kata kunci sebagai bukti bahwa orang benar-benar membeli."
)

with st.sidebar:
    st.header("Pengaturan")

    query = st.text_input(
        "Produk, kategori, atau masalah",
        value="desk organizer",
    )

    region = st.selectbox(
        "Wilayah pencarian berita",
        list(REGIONS.keys()),
    )

    limit = st.slider(
        "Hasil maksimum per sumber",
        min_value=5,
        max_value=30,
        value=10,
    )

    st.markdown("**Sumber**")
    use_news = st.checkbox("Google News RSS", value=True)
    use_hn = st.checkbox("Hacker News", value=True)
    use_ebay = st.checkbox(
        "eBay API (opsional, perlu kredensial)",
        value=False,
    )

    run_button = st.button(
        "🔎 Jalankan riset",
        type="primary",
        use_container_width=True,
    )

st.subheader("Alur riset")
col1, col2, col3 = st.columns(3)
col1.metric("Discovery", "Berita publik")
col2.metric("Diskusi", "Hacker News")
col3.metric("Marketplace", "Opsional")

if run_button:
    if not query.strip():
        st.error("Masukkan kata kunci terlebih dahulu.")
        st.stop()

    with st.spinner("Mencari dan membersihkan data..."):
        result = run_research(
            query=query.strip(),
            region=region,
            limit=limit,
            use_news=use_news,
            use_hn=use_hn,
            use_ebay=use_ebay,
        )

        st.session_state["vanya_records"] = result["records"]
        st.session_state["vanya_errors"] = result["errors"]
        st.session_state["vanya_query"] = query.strip()
        st.session_state["vanya_region"] = region

if "vanya_records" in st.session_state:
    records = st.session_state["vanya_records"]
    errors = st.session_state.get("vanya_errors", [])

    st.divider()
    st.subheader("Hasil riset")

    st.caption(
        f"Kata kunci: {st.session_state['vanya_query']} | "
        f"Wilayah berita: {st.session_state['vanya_region']}"
    )

    if errors:
        with st.expander(f"Catatan sumber ({len(errors)})"):
            for error in errors:
                st.warning(error)

    if not records:
        st.warning(
            "Tidak ada hasil. Coba kata kunci lain atau "
            "periksa koneksi internet."
        )
    else:
        df = pd.DataFrame(records)

        a, b, c = st.columns(3)
        a.metric("Hasil unik", len(df))
        b.metric("Sumber berbeda", df["source"].nunique())
        c.metric(
            "Sinyal keluhan",
            int((df["signal_type"] == "Keluhan").sum()),
        )

        display_df = df.drop(
            columns=["normalized_url"], errors="ignore"
        )

        st.dataframe(
            display_df[
                [
                    "source", "title", "published",
                    "signal_type", "signal_score",
                    "summary", "url",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn(
                    "Sumber",
                    display_text="Buka sumber",
                ),
                "title": st.column_config.TextColumn(
                    "Judul", width="large"
                ),
                "summary": st.column_config.TextColumn(
                    "Ringkasan", width="large"
                ),
                "signal_score": st.column_config.NumberColumn(
                    "Skor sinyal", format="%d"
                ),
            },
        )

        st.caption(
            "Skor sinyal adalah prioritas pemeriksaan berbasis "
            "kata kunci. Ini bukan skor permintaan, penjualan, "
            "atau peluang bisnis."
        )

        st.subheader("Ringkasan otomatis")
        st.markdown(build_summary(df))

        csv_data = df.drop(
            columns=["normalized_url"], errors="ignore"
        ).to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            "⬇️ Ekspor hasil CSV",
            data=csv_data,
            file_name="vanya_research_results.csv",
            mime="text/csv",
        )

st.divider()
st.subheader("Analisis Google Trends")

st.write(
    "Ekspor data Interest over time dari Google Trends, "
    "lalu unggah CSV untuk melihat perubahan indeks."
)

trends_file = st.file_uploader(
    "Unggah CSV Google Trends",
    type=["csv"],
)

if trends_file is not None:
    try:
        trends_df, note = analyze_trends_csv(trends_file)
        st.success(note)
        st.line_chart(
            trends_df.set_index("date")["interest"]
        )
        st.dataframe(
            trends_df,
            use_container_width=True,
            hide_index=True,
        )
    except Exception as exc:
        st.error(f"CSV tidak bisa dianalisis: {exc}")

with st.expander("Batasan dan interpretasi"):
    st.markdown("""
- Google News dan Hacker News dipakai untuk discovery,
  bukan pengukur total permintaan pasar.
- Skor sinyal memakai pencocokan kata kunci sederhana.
- Listing marketplace bukan bukti penjualan aktual.
- Google Trends menggunakan indeks minat relatif, bukan
  volume pencarian absolut.
- Data dari negara atau periode berbeda tidak otomatis
  dapat dibandingkan secara langsung.
- Untuk menyatakan permintaan tinggi dan persaingan rendah,
  kita perlu data kuantitatif yang sebanding.
- Hasil disimpan dalam memori sesi saja, tanpa database
  permanen. Unduh CSV jika ingin menyimpan salinan.
- Patuhi aturan akses, autentikasi, dan batas penggunaan
  setiap sumber.
""")
