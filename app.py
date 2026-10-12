
import io
import json
import re
import sqlite3
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus
from pathlib import Path

import requests
import streamlit as st


# ============================================================
# VANYA SALES AUTOPILOT V2
# Research Memory + Evidence-First Analyst
# ============================================================

APP_NAME = "Vanya Sales Autopilot V2"
DB_PATH = Path("vanya_memory.db")
HEADERS = {"User-Agent": "VanyaSalesAutopilot/2.0"}
TIMEOUT = 12

CATEGORIES = {
    "AI & Automation": [
        "ai", "automation", "agent", "workflow", "chatbot",
        "automate", "artificial intelligence",
    ],
    "Productivity": [
        "productivity", "planning", "task", "organize",
        "time management",
    ],
    "Education": [
        "education", "learning", "student", "course", "tutor",
        "study", "belajar", "pendidikan",
    ],
    "Career": [
        "career", "job", "resume", "portfolio", "interview",
        "freelance", "karier", "pekerjaan",
    ],
    "Creator & Content": [
        "creator", "content", "youtube", "newsletter",
        "social media", "konten", "kreator",
    ],
    "E-commerce": [
        "ecommerce", "e-commerce", "shopify", "online store",
        "seller", "toko online",
    ],
    "Design & Templates": [
        "design", "template", "canva", "notion", "planner",
        "desain",
    ],
    "Research & Data": [
        "research", "analytics", "data", "dashboard", "report",
        "riset", "analisis",
    ],
    "Customer Support": [
        "customer support", "customer service", "helpdesk",
        "ticket", "layanan pelanggan",
    ],
    "Finance Operations": [
        "invoice", "bookkeeping", "budget", "accounting",
        "expense", "keuangan",
    ],
}

PAIN_WORDS = [
    "problem", "pain", "struggle", "difficult", "challenge",
    "frustrating", "need", "looking for", "alternative",
    "masalah", "sulit", "kesulitan", "butuh", "mencari",
    "rekomendasi", "alternatif",
]

SOLUTION_WORDS = [
    "tool", "software", "solution", "product", "service",
    "template", "workflow", "app", "platform", "toolkit",
    "aplikasi", "solusi", "produk", "layanan",
]

PAYMENT_WORDS = [
    "paid", "pay for", "pricing", "subscription", "customer",
    "revenue", "purchase", "buy", "budget", "willingness to pay",
    "berbayar", "harga", "langganan", "membeli", "pelanggan",
]

COMPETITION_WORDS = [
    "competitor", "alternative", "versus", "vs.", "comparison",
    "market leader", "competitor", "alternatif", "perbandingan",
]


# ---------------- DATABASE ----------------

def get_db():
    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=10,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                query TEXT NOT NULL,
                language TEXT NOT NULL,
                result_count INTEGER NOT NULL,
                results_json TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS opportunity_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Unreviewed',
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(category)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS saved_ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                category TEXT NOT NULL,
                product_name TEXT NOT NULL,
                audience TEXT NOT NULL,
                score INTEGER NOT NULL,
                evidence_count INTEGER NOT NULL,
                rationale TEXT NOT NULL DEFAULT ''
            )
        """)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_research(query, language, results):
    with get_db() as db:
        cursor = db.execute("""
            INSERT INTO research_runs
            (created_at, query, language, result_count, results_json)
            VALUES (?, ?, ?, ?, ?)
        """, (
            utc_now(),
            query,
            language,
            len(results),
            json.dumps(results, ensure_ascii=False),
        ))
        return cursor.lastrowid


def load_runs(limit=50):
    with get_db() as db:
        return db.execute("""
            SELECT id, created_at, query, language, result_count
            FROM research_runs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()


def load_run(run_id):
    with get_db() as db:
        row = db.execute("""
            SELECT * FROM research_runs WHERE id = ?
        """, (run_id,)).fetchone()

    if not row:
        return None

    data = dict(row)
    data["results"] = json.loads(data.pop("results_json"))
    return data


def save_note(category, status, notes):
    with get_db() as db:
        db.execute("""
            INSERT INTO opportunity_notes
            (category, status, notes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(category) DO UPDATE SET
                status = excluded.status,
                notes = excluded.notes,
                updated_at = excluded.updated_at
        """, (category, status, notes, utc_now()))


def load_note(category):
    with get_db() as db:
        row = db.execute("""
            SELECT status, notes FROM opportunity_notes
            WHERE category = ?
        """, (category,)).fetchone()

    return dict(row) if row else {
        "status": "Unreviewed",
        "notes": "",
    }


def save_idea(category, product_name, audience, score,
              evidence_count, rationale):
    with get_db() as db:
        db.execute("""
            INSERT INTO saved_ideas
            (created_at, category, product_name, audience,
             score, evidence_count, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            utc_now(), category, product_name, audience,
            score, evidence_count, rationale,
        ))


def load_ideas(limit=100):
    with get_db() as db:
        return db.execute("""
            SELECT * FROM saved_ideas
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()


# ---------------- PUBLIC RESEARCH ----------------

def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


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


def fetch_url(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response


def search_google_news(query, language):
    results = []
    locales = {
        "Indonesia": ("id", "ID", "ID:id"),
        "Global / English": ("en-US", "US", "US:en"),
    }
    lang, country, ceid = locales[language]

    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + f"&hl={lang}&gl={country}&ceid={ceid}"
    )

    try:
        root = ET.fromstring(fetch_url(url).content)

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
        st.warning(f"Google News gagal diakses: {exc}")

    return results


def search_reddit(query):
    results = []

    try:
        response = fetch_url(
            "https://www.reddit.com/search.rss",
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
            link_element = entry.find("atom:link", ns)
            link = (
                link_element.attrib.get("href", "")
                if link_element is not None else ""
            )

            add_result(
                results,
                entry.findtext("atom:title", "", ns),
                link,
                entry.findtext("atom:content", "", ns),
                "Reddit",
                entry.findtext("atom:updated", "", ns),
            )
    except Exception as exc:
        st.warning(f"Reddit gagal diakses: {exc}")

    return results


def search_hacker_news(query):
    results = []

    try:
        response = fetch_url(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": 15,
            },
        )

        for item in response.json().get("hits", []):
            url = item.get("url") or (
                "https://news.ycombinator.com/item?id="
                + str(item.get("objectID", ""))
            )

            add_result(
                results,
                item.get("title", ""),
                url,
                item.get("story_text", "") or "",
                "Hacker News",
                item.get("created_at", ""),
            )
    except Exception as exc:
        st.warning(f"Hacker News gagal diakses: {exc}")

    return results


def research_market(query, language, sources):
    results = []

    if "Google News" in sources:
        results.extend(search_google_news(query, language))

    if "Reddit" in sources:
        results.extend(search_reddit(query))

    if "Hacker News" in sources:
        results.extend(search_hacker_news(query))

    unique = {}
    for item in results:
        unique.setdefault(item["url"], item)

    return list(unique.values())


# ---------------- EVIDENCE ANALYST ----------------

def classify_category(text):
    text = text.lower()
    scores = {
        category: sum(
            1 for keyword in keywords if keyword in text
        )
        for category, keywords in CATEGORIES.items()
    }

    best = max(scores, key=scores.get)
    return best if scores[best] else "General Opportunity"


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
                "pain_hits": 0,
                "solution_hits": 0,
                "payment_hits": 0,
                "competition_hits": 0,
            }

        group = grouped[category]
        group["items"].append(item)
        group["sources"].add(item["source"])
        group["pain_hits"] += sum(
            1 for word in PAIN_WORDS if word in text
        )
        group["solution_hits"] += sum(
            1 for word in SOLUTION_WORDS if word in text
        )
        group["payment_hits"] += sum(
            1 for word in PAYMENT_WORDS if word in text
        )
        group["competition_hits"] += sum(
            1 for word in COMPETITION_WORDS if word in text
        )

    opportunities = []

    for category, data in grouped.items():
        count = len(data["items"])
        source_count = len(data["sources"])

        volume = min(count / 10, 1) * 30
        diversity = min(source_count / 3, 1) * 25
        pain = min(data["pain_hits"] / max(count * 2, 1), 1) * 25
        solution = min(
            data["solution_hits"] / max(count * 2, 1), 1
        ) * 10
        payment = min(
            data["payment_hits"] / max(count, 1), 1
        ) * 10

        score = round(volume + diversity + pain + solution + payment)

        strengths = []
        weaknesses = []

        if count >= 5:
            strengths.append("Ada beberapa hasil yang relevan.")
        else:
            weaknesses.append("Jumlah hasil masih sedikit.")

        if source_count >= 2:
            strengths.append("Sinyal muncul di lebih dari satu sumber.")
        else:
            weaknesses.append("Sumber bukti belum beragam.")

        if data["pain_hits"] > 0:
            strengths.append("Ada istilah yang mungkin menunjukkan masalah pengguna.")
        else:
            weaknesses.append("Masalah pengguna belum terlihat jelas.")

        if data["payment_hits"] > 0:
            strengths.append("Ada istilah terkait harga atau pembayaran.")
        else:
            weaknesses.append("Belum ada sinyal pembayaran yang kuat.")

        if data["competition_hits"] > 0:
            strengths.append("Ada indikasi alternatif atau kompetisi dibahas.")
        else:
            weaknesses.append("Peta kompetisi belum cukup terlihat.")

        opportunities.append({
            "category": category,
            "score": score,
            "result_count": count,
            "source_count": source_count,
            "sources": sorted(data["sources"]),
            "items": data["items"],
            "pain_hits": data["pain_hits"],
            "payment_hits": data["payment_hits"],
            "strengths": strengths,
            "weaknesses": weaknesses,
            "confidence": (
                "Rendah" if count < 4 or source_count < 2
                else "Sedang, belum tervalidasi"
            ),
        })

    return sorted(
        opportunities,
        key=lambda item: item["score"],
        reverse=True,
    )


def local_analyst(opportunity):
    """Transparent fallback that requires no paid AI API."""
    strengths = "\n".join(
        f"- {item}" for item in opportunity["strengths"]
    )
    weaknesses = "\n".join(
        f"- {item}" for item in opportunity["weaknesses"]
    )

    return f"""## Analisis Vanya

**Kategori:** {opportunity['category']}

**Skor prioritas heuristik:** {opportunity['score']}/100

**Kualitas bukti awal:** {opportunity['confidence']}

### Sinyal positif
{strengths}

### Risiko dan bukti yang belum ada
{weaknesses}

### Rekomendasi
Jangan langsung membangun produk penuh. Gunakan temuan ini sebagai
hipotesis. Periksa tautan sumber, baca konteks aslinya, dan cari tahu
apakah masalah tersebut cukup penting bagi calon pengguna.

### Eksperimen berikutnya
1. Wawancarai lima calon pengguna dari audiens yang sama.
2. Tanyakan bagaimana mereka menyelesaikan masalah saat ini.
3. Cari bukti bahwa mereka sudah mengeluarkan uang atau waktu untuk
   mengatasi masalah tersebut.
4. Tunjukkan prototipe sederhana dan minta feedback yang spesifik.
5. Evaluasi hasilnya sebelum menginvestasikan uang.

**Batasan:** analisis ini berbasis aturan dan kata kunci. Ia bukan
model bahasa yang memahami seluruh konteks, dan bukan prediksi omzet.
"""


def ollama_analyst(opportunity, endpoint, model):
    prompt = f"""
You are a skeptical digital business research analyst.
Analyze only the evidence supplied below. Do not invent facts,
market size, prices, competitors, or willingness to pay.
Clearly separate observed evidence from hypotheses.
If evidence is weak, say so.
Recommend the cheapest experiment that could disprove the idea.

Category: {opportunity['category']}
Heuristic score: {opportunity['score']}/100
Source diversity: {opportunity['source_count']}
Evidence count: {opportunity['result_count']}

Evidence:
{json.dumps(opportunity['items'][:8], ensure_ascii=False)}

Return:
1. Evidence-backed signals
2. Weaknesses and missing evidence
3. Competitor questions to investigate
4. Cheapest validation experiment
5. Recommendation: investigate, test, or deprioritize
"""

    response = requests.post(
        endpoint.rstrip("/") + "/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json().get("response", "").strip()


# ---------------- PRODUCT WORKSPACE ----------------

def make_product_plan(opportunity, audience, format_type):
    category = opportunity["category"]
    name = f"{category}: Starter Kit"

    listing = f"""# {name}

## Target audience
{audience}

## Product concept
A practical digital resource related to {category}.
This is a hypothesis to validate, not a proven market opportunity.

## Planned format
{format_type}

## Proposed contents
- Step-by-step guide
- Customizable templates
- Practical examples
- Implementation checklist

## Before launch
- Interview potential users.
- Test a small prototype.
- Verify all claims and make original material.
- Test willingness to pay before setting a price.
"""

    faq = """# FAQ Draft

**Who is this for?**
Users whose needs match the final product description.

**Are results guaranteed?**
No. Outcomes depend on the user and how the material is applied.

**Can it be customized?**
Describe actual customization options once the product is finished.

**How is it delivered?**
Add delivery instructions after choosing a sales platform.
"""

    calendar = """# 7-Day Content Calendar

1. Explain the audience's core problem.
2. Share a practical tip.
3. Discuss a common mistake.
4. Publish a short tutorial.
5. Show a prototype example.
6. Answer audience questions.
7. Invite feedback or beta testers.
"""

    validation = """# Validation Plan

1. Interview at least five potential users.
2. Learn what solutions they use today.
3. Ask about time, money, and friction.
4. Build a small prototype.
5. Test whether people actually use it.
6. Test willingness to pay ethically and transparently.
7. Decide whether to continue, revise, or stop.
"""

    report = [
        "# Research Report",
        "",
        f"Generated: {utc_now()}",
        f"Category: {category}",
        f"Heuristic score: {opportunity['score']}/100",
        f"Confidence: {opportunity['confidence']}",
        "",
        "> This score is not a sales forecast. Search results do not",
        "> prove demand, market size, or willingness to pay.",
    ]

    for item in opportunity["items"]:
        report.extend([
            "",
            f"## {item['title']}",
            f"- Source: {item['source']}",
            f"- URL: {item['url']}",
            f"- Date: {item['date'] or 'Not provided'}",
            f"- Summary: {item['summary'] or 'No summary available'}",
        ])

    strategy = {
        "product_name": name,
        "category": category,
        "audience": audience,
        "format": format_type,
        "heuristic_score": opportunity["score"],
        "confidence": opportunity["confidence"],
        "evidence_count": opportunity["result_count"],
        "sources": opportunity["sources"],
        "generated_at": utc_now(),
    }

    return {
        "strategy.json": json.dumps(
            strategy, indent=2, ensure_ascii=False
        ),
        "market_research_report.md": "\n".join(report),
        "product_draft.md": listing,
        "listing_draft.md": listing,
        "faq_draft.md": faq,
        "content_calendar.md": calendar,
        "validation_plan.md": validation,
    }


def make_zip(files):
    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr(
            "START_HERE.md",
            """# Vanya Workspace

These are research notes and product drafts, not a finished product.

Review source links, verify claims, test demand, and check licensing.
No product has been published and no revenue is guaranteed.
""",
        )

        for name, content in files.items():
            archive.writestr(name, content)

    buffer.seek(0)
    return buffer.getvalue()


# ---------------- APP ----------------

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🧭",
    layout="wide",
)

init_db()

st.title("🧭 Vanya Sales Autopilot V2")
st.caption("Research Memory + Evidence-First Analyst")

with st.sidebar:
    st.header("Market Scout")

    query = st.text_input(
        "Topik pencarian",
        value="AI tools for small business",
    )

    language = st.selectbox(
        "Bahasa",
        ["Indonesia", "Global / English"],
    )

    sources = st.multiselect(
        "Sumber publik",
        ["Google News", "Reddit", "Hacker News"],
        default=["Google News", "Reddit", "Hacker News"],
    )

    run_search = st.button(
        "🔎 Cari dan simpan riset",
        type="primary",
        use_container_width=True,
    )

    st.divider()
    st.header("AI Analyst")

    analyst_mode = st.selectbox(
        "Mode analisis",
        ["Rule-based (gratis)", "Ollama lokal"],
    )

    ollama_endpoint = st.text_input(
        "Ollama endpoint",
        value="http://localhost:11434",
        help=(
            "Gunakan localhost saat Streamlit berjalan di komputer "
            "yang sama dengan Ollama. Bukan localhost komputer lu "
            "kalau aplikasi berjalan di cloud."
        ),
    )

    ollama_model = st.text_input(
        "Nama model Ollama",
        value="llama3.2",
    )

st.info(
    "Vanya hanya meneliti, menganalisis, dan membuat draft. "
    "Tidak ada transaksi atau publikasi otomatis."
)

if run_search:
    if not query.strip():
        st.error("Isi topik pencarian terlebih dahulu.")
    elif not sources:
        st.error("Pilih minimal satu sumber.")
    else:
        with st.spinner("Mengumpulkan bukti dari sumber publik..."):
            results = research_market(
                query.strip(), language, sources
            )
            opportunities = score_opportunities(results)

        run_id = save_research(query.strip(), language, results)

        st.session_state["current_run_id"] = run_id
        st.session_state["current_results"] = results
        st.session_state["current_opportunities"] = opportunities

        st.success(
            f"Riset tersimpan di Memory. ID riset: {run_id}"
        )

if "current_opportunities" in st.session_state:
    opportunities = st.session_state["current_opportunities"]
    results = st.session_state["current_results"]

    st.subheader("📊 Opportunity Ranking")

    c1, c2, c3 = st.columns(3)
    c1.metric("Hasil", len(results))
    c2.metric("Kategori", len(opportunities))
    c3.metric(
        "Sumber berbeda",
        len(set(item["source"] for item in results)),
    )

    if not opportunities:
        st.warning(
            "Belum ada hasil. Coba kata kunci berbeda atau "
            "periksa lagi nanti."
        )

    for index, opportunity in enumerate(opportunities, start=1):
        with st.expander(
            f"{index}. {opportunity['category']} | "
            f"{opportunity['score']}/100 | "
            f"{opportunity['result_count']} hasil",
            expanded=(index == 1),
        ):
            st.write(
                f"**Kualitas bukti awal:** "
                f"{opportunity['confidence']}"
            )

            left, right = st.columns(2)

            with left:
                st.markdown("**Sinyal positif**")
                for item in opportunity["strengths"]:
                    st.write(f"• {item}")

            with right:
                st.markdown("**Kelemahan bukti**")
                for item in opportunity["weaknesses"]:
                    st.write(f"• {item}")

            st.markdown("**Sumber asli**")

            for item in opportunity["items"][:8]:
                st.markdown(f"- [{item['title']}]({item['url']})")
                if item["summary"]:
                    st.caption(item["summary"][:300])

            if st.button(
                "🧠 Analisis kategori ini",
                key=f"analyse_{st.session_state['current_run_id']}_{index}",
            ):
                with st.spinner("Menganalisis bukti..."):
                    try:
                        if analyst_mode == "Ollama lokal":
                            analysis = ollama_analyst(
                                opportunity,
                                ollama_endpoint,
                                ollama_model,
                            )
                        else:
                            analysis = local_analyst(opportunity)

                        st.session_state[
                            f"analysis_{st.session_state['current_run_id']}_{index}"
                        ] = analysis
                    except Exception as exc:
                        st.error(
                            "Analisis AI gagal. Pastikan Ollama "
                            "berjalan dan model sudah tersedia. "
                            f"Detail: {exc}"
                        )

            analysis_key = (
                f"analysis_{st.session_state['current_run_id']}_{index}"
            )

            if analysis_key in st.session_state:
                st.markdown(st.session_state[analysis_key])

st.divider()
st.subheader("🗂️ Research Memory")

runs = load_runs()

if not runs:
    st.write("Belum ada riwayat. Jalankan riset pertama lu dulu.")
else:
    st.write(f"Total riwayat yang tersedia: {len(runs)}")

    run_options = {
        f"#{row['id']} | {row['created_at']} | "
        f"{row['query']} ({row['result_count']} hasil)": row["id"]
        for row in runs
    }

    chosen_run_label = st.selectbox(
        "Buka riwayat riset",
        list(run_options.keys()),
    )

    if st.button("Buka riwayat"):
        saved_run = load_run(run_options[chosen_run_label])

        if saved_run:
            st.session_state["opened_saved_run"] = saved_run

    if "opened_saved_run" in st.session_state:
        saved_run = st.session_state["opened_saved_run"]

        st.markdown(f"**Topik:** {saved_run['query']}")
        st.caption(
            f"Dibuat: {saved_run['created_at']} · "
            f"{saved_run['result_count']} hasil"
        )

        for item in saved_run["results"]:
            st.markdown(f"- [{item['title']}]({item['url']})")
            st.caption(item["source"])

st.divider()
st.subheader("📝 Business Decision Log")

if "current_opportunities" in st.session_state:
    decision_categories = [
        item["category"]
        for item in st.session_state["current_opportunities"]
    ]

    selected_note_category = st.selectbox(
        "Kategori yang mau dicatat",
        decision_categories,
    )

    existing_note = load_note(selected_note_category)

    with st.form("decision_form"):
        status = st.selectbox(
            "Status keputusan",
            [
                "Unreviewed",
                "Investigating",
                "Validate with users",
                "Promising",
                "Rejected",
                "Building prototype",
            ],
            index=[
                "Unreviewed",
                "Investigating",
                "Validate with users",
                "Promising",
                "Rejected",
                "Building prototype",
            ].index(existing_note["status"]),
        )

        notes = st.text_area(
            "Alasan, eksperimen, atau hasil validasi",
            value=existing_note["notes"],
            placeholder=(
                "Contoh: sudah bicara dengan 3 calon pengguna; "
                "2 orang mengalami masalah yang sama."
            ),
        )

        save_decision = st.form_submit_button(
            "Simpan keputusan"
        )

        if save_decision:
            save_note(selected_note_category, status, notes)
            st.success("Keputusan tersimpan di Research Memory.")
else:
    st.caption(
        "Jalankan riset dan pilih kategori untuk mulai mencatat keputusan."
    )

st.divider()
st.subheader("💾 Saved Product Ideas")

with st.form("idea_form"):
    idea_category = st.text_input(
        "Kategori ide",
        placeholder="Contoh: AI & Automation",
    )
    product_name = st.text_input("Nama konsep produk")
    audience = st.text_input("Target pengguna")
    rationale = st.text_area(
        "Alasan menyimpan ide",
        placeholder="Bukti pendukung, risiko, dan eksperimen berikutnya",
    )
    save_idea_button = st.form_submit_button("Simpan ide")

    if save_idea_button:
        if product_name.strip() and idea_category.strip():
            save_idea(
                idea_category.strip(),
                product_name.strip(),
                audience.strip() or "Belum ditentukan",
                0,
                0,
                rationale.strip(),
            )
            st.success("Ide tersimpan.")
        else:
            st.error("Isi minimal kategori dan nama konsep produk.")

ideas = load_ideas()

if ideas:
    for idea in ideas:
        with st.expander(
            f"{idea['product_name']} · {idea['category']}"
        ):
            st.write(f"Target: {idea['audience']}")
            st.write(f"Catatan: {idea['rationale'] or 'Belum ada'}")
            st.caption(f"Dibuat: {idea['created_at']}")
            
# ---------------- PRODUCT PLANNER + ZIP EXPORT ----------------

st.subheader("📦 Product Planner & Export")

if "current_opportunities" in st.session_state:
    current_opportunities = st.session_state["current_opportunities"]

    if current_opportunities:
        planner_category = st.selectbox(
            "Peluang untuk dijadikan draft produk",
            [
                item["category"]
                for item in current_opportunities
            ],
            key="planner_category",
        )

        planner_audience = st.text_input(
            "Target pengguna produk",
            value="Pemilik bisnis kecil dan solo entrepreneur",
            key="planner_audience",
        )

        planner_format = st.selectbox(
            "Format produk",
            [
                "PDF guide + templates",
                "Notion template",
                "Spreadsheet toolkit",
                "Mini course outline",
                "Prompt pack",
                "Web app concept",
            ],
            key="planner_format",
        )

        if st.button(
            "Buat workspace produk",
            type="primary",
            key="make_product_workspace",
        ):
            selected = next(
                item for item in current_opportunities
                if item["category"] == planner_category
            )

            st.session_state["product_workspace"] = make_product_plan(
                selected,
                planner_audience.strip() or "General users",
                planner_format,
            )

            st.session_state["workspace_category"] = planner_category
            st.success("Draft workspace berhasil dibuat.")

if "product_workspace" in st.session_state:
    workspace = st.session_state["product_workspace"]

    for filename, content in workspace.items():
        with st.expander(filename):
            st.markdown(content)

    st.download_button(
        "⬇️ Download workspace ZIP",
        data=make_zip(workspace),
        file_name="vanya_workspace.zip",
        mime="application/zip",
        type="primary",
    )
else:
    st.caption(
        "Jalankan riset terlebih dahulu untuk membuat draft produk."
    )


st.divider()
st.caption(
    "Vanya V2 · Research assistance only · "
    "Scores are heuristics · Human approval required"
)
