
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone 
from urllib.parse import quote_plus

import requests
import streamlit as st


# ==========================================
# VANYA SALES AUTOPILOT - WEB MVP
# ==========================================

APP_NAME = "Vanya Sales Autopilot"
HEADERS = {
    "User-Agent": "VanyaSalesAutopilot/1.0 (market research prototype)"
}
TIMEOUT = 12

CATEGORIES = {
    "AI & Automation": [
        "ai", "automation", "agent", "workflow", "chatbot", "automate"
    ],
    "Productivity": [
        "productivity", "planning", "task", "organize", "time management"
    ],
    "Education": [
        "education", "learning", "student", "course", "tutor", "study"
    ],
    "Career": [
        "career", "job", "resume", "portfolio", "interview", "freelance"
    ],
    "Creator & Content": [
        "creator", "content", "youtube", "newsletter", "social media"
    ],
    "E-commerce": [
        "ecommerce", "e-commerce", "shopify", "online store", "seller"
    ],
    "Design & Templates": [
        "design", "template", "canva", "notion", "planner"
    ],
    "Research & Data": [
        "research", "analytics", "data", "dashboard", "report"
    ],
    "Customer Support": [
        "customer support", "customer service", "helpdesk", "ticket"
    ],
    "Finance Operations": [
        "invoice", "bookkeeping", "budget", "accounting", "expense"
    ],
}


# ---------- GENERAL HELPERS ----------

def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def fetch_url(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response


def add_result(results, title, url, summary, source, date=""):
    title = clean_html(title)
    summary = clean_html(summary)

    if not title or not url:
        return

    if not url.startswith(("https://", "http://")):
        return

    results.append({
        "title": title[:300],
        "url": url,
        "summary": summary[:700],
        "source": source,
        "date": str(date or ""),
    })


# ---------- PUBLIC SOURCE RESEARCH ----------

def search_google_news(query, language):
    results = []
    locale = {
        "Indonesia": ("id", "ID", "ID:id"),
        "Global / English": ("en-US", "US", "US:en"),
    }
    lang, country, ceid = locale[language]

    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + f"&hl={lang}&gl={country}&ceid={ceid}"
    )

    try:
        response = fetch_url(url)
        root = ET.fromstring(response.content)

        for item in root.findall(".//item")[:15]:
            add_result(
                results,
                item.findtext("title", ""),
                item.findtext("link", ""),
                item.findtext("description", ""),
                "Google News",
                item.findtext("pubDate", ""),
            )
    except Exception as exc:
        st.warning(f"Google News tidak bisa diakses: {exc}")

    return results


def search_hacker_news(query):
    results = []
    url = "https://hn.algolia.com/api/v1/search"

    try:
        response = fetch_url(
            url,
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": 15,
            },
        )
        data = response.json()

        for item in data.get("hits", []):
            story_url = item.get("url")
            if not story_url:
                story_url = (
                    "https://news.ycombinator.com/item?id="
                    + str(item.get("objectID", ""))
                )

            add_result(
                results,
                item.get("title", ""),
                story_url,
                item.get("story_text") or "",
                "Hacker News",
                item.get("created_at", ""),
            )
    except Exception as exc:
        st.warning(f"Hacker News tidak bisa diakses: {exc}")

    return results


def search_reddit(query):
    results = []
    url = "https://www.reddit.com/search.rss"

    try:
        response = fetch_url(
            url,
            params={
                "q": query,
                "sort": "relevance",
                "limit": 15,
                "t": "year",
            },
        )
        root = ET.fromstring(response.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns)[:15]:
            title = entry.findtext("atom:title", "", ns)
            link_element = entry.find("atom:link", ns)
            link = (
                link_element.attrib.get("href", "")
                if link_element is not None
                else ""
            )
            summary = entry.findtext("atom:content", "", ns)
            published = entry.findtext("atom:updated", "", ns)

            add_result(
                results,
                title,
                link,
                summary,
                "Reddit",
                published,
            )
    except Exception as exc:
        st.warning(
            "Reddit tidak bisa diakses saat ini. "
            f"Sumber lain tetap bisa digunakan. Detail: {exc}"
        )

    return results


def research_market(query, language, sources):
    results = []

    if "Google News" in sources:
        results.extend(search_google_news(query, language))

    if "Reddit" in sources:
        results.extend(search_reddit(query))

    if "Hacker News" in sources:
        results.extend(search_hacker_news(query))

    # Remove duplicate URLs.
    unique = {}
    for item in results:
        unique.setdefault(item["url"], item)

    return list(unique.values())


# ---------- OPPORTUNITY SCORING ----------

def classify_category(text):
    text = text.lower()
    scores = {}

    for category, keywords in CATEGORIES.items():
        scores[category] = sum(
            1 for keyword in keywords if keyword in text
        )

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "General Opportunity"


def score_opportunities(results):
    grouped = {}

    for item in results:
        text = (
            item["title"] + " " + item["summary"]
        ).lower()
        category = classify_category(text)

        if category not in grouped:
            grouped[category] = {
                "category": category,
                "items": [],
                "sources": set(),
                "keyword_hits": 0,
            }

        grouped[category]["items"].append(item)
        grouped[category]["sources"].add(item["source"])

        signal_words = [
            "problem", "need", "challenge", "difficult",
            "alternative", "looking for", "how to",
            "solution", "tool", "automate", "workflow",
            "struggle", "recommend", "save time",
        ]

        grouped[category]["keyword_hits"] += sum(
            1 for word in signal_words if word in text
        )

    opportunities = []

    for category, data in grouped.items():
        count = len(data["items"])
        source_count = len(data["sources"])

        # Heuristic score, NOT a sales forecast.
        volume_score = min(count / 10, 1) * 40
        diversity_score = min(source_count / 3, 1) * 30
        signal_score = min(
            data["keyword_hits"] / max(count * 2, 1), 1
        ) * 30

        score = round(
            volume_score + diversity_score + signal_score
        )

        opportunities.append({
            "category": category,
            "score": score,
            "result_count": count,
            "source_count": source_count,
            "sources": sorted(data["sources"]),
            "items": data["items"],
            "evidence": (
                f"{count} hasil riset, "
                f"{source_count} sumber berbeda."
            ),
        })

    return sorted(
        opportunities,
        key=lambda item: item["score"],
        reverse=True,
    )


# ---------- PRODUCT PLANNER ----------

def make_product_plan(opportunity, audience, format_type, language):
    category = opportunity["category"]
    top_items = opportunity["items"][:8]

    titles = [item["title"] for item in top_items]

    if language == "Indonesia":
        product_name = f"{category}: Starter Kit"
        product_description = (
            f"Konsep produk digital untuk membantu {audience} "
            f"mengatasi kebutuhan yang berkaitan dengan {category}. "
            "Validasi kebutuhan calon pembeli sebelum membuat "
            "produk final."
        )
        listing = f"""# {product_name}

## Untuk siapa?
{audience}

## Gambaran produk
{product_description}

## Format
{format_type}

## Isi yang direncanakan
- Panduan langkah demi langkah
- Template yang bisa disesuaikan
- Contoh penggunaan
- Checklist implementasi

## Sebelum diluncurkan
- Wawancarai calon pengguna.
- Uji prototipe dengan beberapa orang.
- Pastikan materi original dan punya manfaat nyata.
- Tentukan harga setelah menguji minat pembeli.
"""
        faq = """# FAQ Draft

**Produk ini cocok untuk siapa?**
Untuk pengguna yang kebutuhannya sesuai dengan deskripsi produk.

**Apakah hasilnya dijamin?**
Tidak. Hasil bergantung pada kebutuhan dan cara penggunaan.

**Apakah produk bisa disesuaikan?**
Jelaskan bagian mana yang bisa diedit setelah format final ditentukan.

**Bagaimana cara mendapatkan produk?**
Tambahkan instruksi pengiriman setelah platform penjualan dipilih.
"""
        calendar = """# Kalender Konten 7 Hari

1. Bahas masalah utama audiens.
2. Bagikan tips praktis yang bisa langsung dicoba.
3. Jelaskan kesalahan umum.
4. Publikasikan tutorial singkat.
5. Tampilkan contoh penggunaan prototipe.
6. Jawab pertanyaan calon pengguna.
7. Ajak audiens memberi feedback atau mencoba versi beta.
"""
        validation = """# Rencana Validasi

1. Bicara dengan minimal 5 calon pengguna.
2. Cari tahu solusi yang mereka pakai sekarang.
3. Tanyakan biaya, waktu, atau kesulitan dari solusi tersebut.
4. Buat prototipe sederhana.
5. Uji apakah pengguna benar-benar mau menggunakannya.
6. Evaluasi minat sebelum memutuskan harga dan peluncuran.
"""
    else:
        product_name = f"{category}: Starter Kit"
        product_description = (
            f"A digital product concept for {audience} "
            f"related to {category}. Validate demand before "
            "building the complete product."
        )
        listing = f"""# {product_name}

## Target audience
{audience}

## Product concept
{product_description}

## Format
{format_type}

## Planned contents
- Step-by-step guide
- Customizable templates
- Usage examples
- Implementation checklist

## Before launch
- Interview potential users.
- Test a prototype.
- Ensure the material is original and useful.
- Set a price only after testing buyer interest.
"""
        faq = """# FAQ Draft

**Who is this for?**
Users whose needs match the product description.

**Are results guaranteed?**
No. Results depend on user needs and implementation.

**Can it be customized?**
Specify customization options after finalizing the format.

**How is it delivered?**
Add delivery instructions once a sales platform is selected.
"""
        calendar = """# 7-Day Content Calendar

1. Discuss the audience's core problem.
2. Share a practical tip.
3. Explain a common mistake.
4. Publish a short tutorial.
5. Show a prototype example.
6. Answer audience questions.
7. Invite feedback or beta testers.
"""
        validation = """# Validation Plan

1. Interview at least five potential users.
2. Learn what solutions they use today.
3. Understand the costs and friction of those solutions.
4. Build a small prototype.
5. Test whether people actually use it.
6. Evaluate demand before setting a price or launching.
"""

    research_report = [
        "# Market Research Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Selected category: {category}",
        f"Heuristic score: {opportunity['score']}/100",
        f"Evidence count: {opportunity['result_count']}",
        f"Source diversity: {opportunity['source_count']}",
        "",
        "> This score is a rough prioritization heuristic, not a",
        "> demand forecast, proof of willingness to pay, or guarantee",
        "> of revenue. Search results may be incomplete or biased.",
        "",
        "## Source evidence",
    ]

    for item in opportunity["items"]:
        research_report.extend([
            "",
            f"### {item['title']}",
            f"- Source: {item['source']}",
            f"- Date: {item['date'] or 'Not provided'}",
            f"- URL: {item['url']}",
            f"- Summary: {item['summary'] or 'No summary available'}",
        ])

    strategy = {
        "product_name": product_name,
        "category": category,
        "audience": audience,
        "format": format_type,
        "heuristic_score": opportunity["score"],
        "evidence_count": opportunity["result_count"],
        "sources": opportunity["sources"],
        "product_description": product_description,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Heuristic score is not a sales forecast.",
            "Search results do not prove willingness to pay.",
            "Sources can be incomplete or unavailable.",
            "Validate demand before investing money.",
        ],
    }

    return {
        "strategy.json": json.dumps(
            strategy, indent=2, ensure_ascii=False
        ),
        "market_research_report.md": "\n".join(research_report),
        "product_draft.md": (
            f"# {product_name}\n\n{product_description}\n\n"
            "## Proposed outline\n"
            "1. Introduction\n"
            "2. Core method\n"
            "3. Practical examples\n"
            "4. Templates or exercises\n"
            "5. Implementation checklist\n\n"
            "This is a concept draft, not a finished product."
        ),
        "listing_draft.md": listing,
        "faq_draft.md": faq,
        "content_calendar.md": calendar,
        "validation_plan.md": validation,
    }


def create_workspace(files):
    memory_file = io.BytesIO()

    with zipfile.ZipFile(
        memory_file, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "START_HERE.md",
            """# Vanya Sales Autopilot Workspace

This package contains research evidence and product drafts.

## Important
- Research signals are not proof of demand.
- Verify all source links and facts.
- Validate the idea with potential users.
- Review originality, licensing, and platform policies.
- No product has been published and no sales have been made.
""",
        )

        for filename, content in files.items():
            archive.writestr(filename, content)

    memory_file.seek(0)
    return memory_file.getvalue()


# ---------- STREAMLIT USER INTERFACE ----------

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🧭",
    layout="wide",
)

st.title("🧭 Vanya Sales Autopilot")
st.caption(
    "Market research → opportunity ranking → product drafts. "
    "Lu tetap memegang kendali."
)

with st.sidebar:
    st.header("Market Scout")

    query = st.text_input(
        "Topik atau masalah",
        value="AI tools for small business",
        help="Contoh: Notion templates, study planner, AI customer support.",
    )

    language = st.selectbox(
        "Bahasa pencarian",
        ["Indonesia", "Global / English"],
    )

    sources = st.multiselect(
        "Sumber publik",
        ["Google News", "Reddit", "Hacker News"],
        default=["Google News", "Reddit", "Hacker News"],
    )

    run_research = st.button(
        "🔎 Cari peluang",
        type="primary",
        use_container_width=True,
    )

st.info(
    "Privasi: aplikasi ini tidak meminta password marketplace atau "
    "API key. Query dikirim ke sumber publik yang dipilih. "
    "Jangan masukkan informasi pribadi atau rahasia."
)

if run_research:
    if not query.strip():
        st.error("Masukkan topik pencarian terlebih dahulu.")
    elif not sources:
        st.error("Pilih setidaknya satu sumber.")
    else:
        with st.spinner("Vanya sedang mencari sinyal pasar..."):
            results = research_market(
                query.strip(), language, sources
            )
            opportunities = score_opportunities(results)

        st.session_state["vanya_results"] = results
        st.session_state["vanya_opportunities"] = opportunities
        st.session_state["vanya_query"] = query.strip()

if "vanya_opportunities" in st.session_state:
    opportunities = st.session_state["vanya_opportunities"]
    results = st.session_state["vanya_results"]

    st.subheader("📊 Hasil Market Scout")

    col1, col2, col3 = st.columns(3)
    col1.metric("Hasil riset", len(results))
    col2.metric("Kategori terdeteksi", len(opportunities))
    col3.metric(
        "Sumber terwakili",
        len(set(item["source"] for item in results)),
    )

    if not opportunities:
        st.warning(
            "Belum ada hasil yang bisa dianalisis. "
            "Coba query lain atau jalankan pencarian lagi nanti."
        )
    else:
        st.caption(
            "Skor hanya untuk membantu menyusun prioritas, bukan "
            "prediksi penjualan. Hasil pencarian yang sedikit "
            "tidak berarti pasar pasti buruk."
        )

        for index, opportunity in enumerate(opportunities, start=1):
            with st.expander(
                f"{index}. {opportunity['category']} | "
                f"Skor {opportunity['score']}/100 | "
                f"{opportunity['result_count']} hasil",
                expanded=(index == 1),
            ):
                st.write(opportunity["evidence"])
                st.write(
                    "Sumber: " + ", ".join(opportunity["sources"])
                )

                for item in opportunity["items"][:8]:
                    st.markdown(f"**[{item['title']}]({item['url']})**")
                    if item["summary"]:
                        st.write(item["summary"][:350])
                    st.caption(
                        f"{item['source']} · {item['date'] or 'Tanggal tidak tersedia'}"
                    )

        st.divider()
        st.subheader("🧠 Product Planner")

        category_names = [
            item["category"] for item in opportunities
        ]

        selected_category = st.selectbox(
            "Pilih peluang untuk dikembangkan",
            category_names,
        )

        audience = st.text_input(
            "Target pengguna",
            value="Pemilik bisnis kecil dan solo entrepreneur",
        )

        format_type = st.selectbox(
            "Format produk",
            [
                "PDF guide + templates",
                "Notion template",
                "Spreadsheet toolkit",
                "Mini course outline",
                "Prompt pack",
                "Web app concept",
            ],
        )

        selected_opportunity = next(
            item for item in opportunities
            if item["category"] == selected_category
        )

        if st.button(
            "🛠️ Buat product workspace",
            type="primary",
        ):
            draft_files = make_product_plan(
                selected_opportunity,
                audience.strip() or "General users",
                format_type,
                language,
            )

            st.session_state["vanya_drafts"] = draft_files
            st.success(
                "Workspace draft selesai. Periksa isinya sebelum digunakan."
            )

if "vanya_drafts" in st.session_state:
    st.divider()
    st.subheader("📦 Workspace Export")

    draft_files = st.session_state["vanya_drafts"]

    for filename, content in draft_files.items():
        with st.expander(filename):
            st.markdown(content)

    zip_data = create_workspace(draft_files)

    st.download_button(
        label="⬇️ Download semua hasil (.zip)",
        data=zip_data,
        file_name="vanya_workspace.zip",
        mime="application/zip",
        type="primary",
    )

st.divider()
st.caption(
    "Vanya MVP · Research and drafting only · "
    "No automatic purchases, publishing, or financial actions."
)
