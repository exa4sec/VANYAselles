
import re
import html
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode
import xml.etree.ElementTree as ET

import requests
import streamlit as st


# =========================================================
# VANYA RESEARCH ENGINE v1
# Multi-source research, evidence filtering, no database.
# =========================================================

APP_NAME = "Vanya Research Engine"
TIMEOUT = 15
MAX_PER_QUERY = 25

HEADERS = {
    "User-Agent": "VanyaResearchEngine/1.0 (public research dashboard)"
}

PAIN_TERMS = {
    "difficulty": [
        "struggling", "struggle", "difficult", "difficulty",
        "problem", "problems", "issue", "issues", "frustrated",
        "frustrating", "annoying", "pain point", "broken",
        "kesulitan", "masalah", "susah", "sulit", "ribet",
        "merepotkan", "keluhan", "gangguan", "gagal",
    ],
    "repeated_need": [
        "every day", "every week", "constantly", "keep having",
        "always have to", "takes hours", "waste time",
        "berulang kali", "setiap hari", "setiap minggu",
        "buang waktu", "berkali-kali",
    ],
    "workaround": [
        "workaround", "currently use", "instead i use",
        "instead we use", "manually", "spreadsheet",
        "manual process", "currently paying for",
        "alternatif", "cara manual", "pakai excel",
        "mengakalinya", "sementara menggunakan",
    ],
    "payment": [
        "paid for", "paying for", "willing to pay",
        "subscription", "pricing", "costs me", "cost per month",
        "expensive", "too expensive", "customer pays",
        "membayar", "berbayar", "biaya bulanan",
        "mahal", "langganan", "harga",
    ],
    "solution_request": [
        "any tool", "any app", "any software", "recommend a tool",
        "looking for a tool", "is there a way", "how do you solve",
        "need a tool", "need help", "looking for a solution",
        "ada aplikasi", "butuh bantuan", "mencari solusi",
        "ada cara", "rekomendasi aplikasi",
    ],
    "counterevidence": [
        "solved", "problem solved", "no longer an issue",
        "free alternative", "easy to fix", "doesn't matter",
        "not a problem anymore", "sudah teratasi",
        "tidak masalah lagi", "sudah selesai",
    ],
}

CATEGORY_TERMS = {
    "Pekerjaan & produktivitas": [
        "work", "job", "employee", "office", "workflow",
        "productivity", "meeting", "task", "project", "business",
        "kerja", "pekerjaan", "karyawan", "kantor", "usaha",
        "produktivitas",
    ],
    "Pendidikan": [
        "school", "student", "teacher", "learning", "study",
        "homework", "course", "education", "belajar", "sekolah",
        "siswa", "guru", "kuliah",
    ],
    "Teknologi & software": [
        "software", "app", "application", "website", "computer",
        "phone", "AI", "automation", "bug", "platform", "API",
        "aplikasi", "situs", "komputer", "teknologi",
    ],
    "Keuangan & administrasi": [
        "money", "finance", "budget", "invoice", "tax",
        "accounting", "payment", "bill", "uang", "keuangan",
        "anggaran", "tagihan", "pembukuan",
    ],
    "Pelanggan & belanja": [
        "customer", "client", "shopping", "buyer", "seller",
        "delivery", "product", "refund", "pelanggan", "pembeli",
        "penjual", "belanja", "pengiriman",
    ],
    "Kesehatan & keseharian": [
        "health", "sleep", "food", "fitness", "stress",
        "daily life", "family", "doctor", "kesehatan",
        "tidur", "makanan", "keluarga",
    ],
}


def clean_text(value):
    if not value:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalized_url(url):
    """Remove tracking query parameters for basic deduplication."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ""
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/")
        return f"https://{host}{path}"
    except Exception:
        return ""


def domain_of(url):
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def matches_any(text, terms):
    text = text.lower()
    return [term for term in terms if term.lower() in text]


def classify_category(text):
    text = text.lower()
    scores = {
        category: len(matches_any(text, terms))
        for category, terms in CATEGORY_TERMS.items()
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "Kategori belum diketahui"
    return best


def is_reddit_root(url):
    """A subreddit homepage is not a specific user's problem report."""
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) == 2 and parts[0].lower() == "r":
            return True
        if len(parts) == 1 and parts[0].lower() in ("reddit.com", ""):
            return True
        return False
    except Exception:
        return True


def is_specific_reddit_post(url):
    path = urlparse(url).path.lower()
    return "/comments/" in path


def make_record(title, url, snippet, source, date="", kind=""):
    title = clean_text(title)
    snippet = clean_text(snippet)
    url = str(url or "").strip()
    canonical = normalized_url(url)

    if not title or not canonical:
        return None

    return {
        "title": title,
        "url": url,
        "canonical_url": canonical,
        "snippet": snippet[:1600],
        "source": source,
        "domain": domain_of(url),
        "date": str(date or ""),
        "kind": kind,
    }


def fetch_gdelt(query):
    """Public news index. News is context, not proof of personal demand."""
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": MAX_PER_QUERY,
        "sort": "HybridRel",
    }

    try:
        response = requests.get(
            endpoint, params=params, headers=HEADERS, timeout=TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        records = []

        for item in data.get("articles", []):
            record = make_record(
                item.get("title", ""),
                item.get("url", ""),
                item.get("title", ""),
                "GDELT News",
                item.get("seendate", ""),
                "news",
            )
            if record:
                records.append(record)
        return records, None
    except Exception as exc:
        return [], f"GDELT: {type(exc).__name__}: {exc}"


def fetch_hacker_news(query):
    """Search public Hacker News stories through Algolia."""
    endpoint = "https://hn.algolia.com/api/v1/search_by_date"
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": MAX_PER_QUERY,
    }

    try:
        response = requests.get(
            endpoint, params=params, headers=HEADERS, timeout=TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        records = []

        for item in data.get("hits", []):
            story_id = item.get("objectID", "")
            url = item.get("url") or (
                f"https://news.ycombinator.com/item?id={story_id}"
            )
            title = item.get("title") or ""
            snippet = item.get("story_text") or title
            record = make_record(
                title, url, snippet, "Hacker News",
                item.get("created_at", ""), "discussion_or_story"
            )
            if record:
                records.append(record)
        return records, None
    except Exception as exc:
        return [], f"Hacker News: {type(exc).__name__}: {exc}"


def fetch_reddit(query):
    """Public Reddit RSS search. Availability may vary by region and policy."""
    endpoint = "https://www.reddit.com/search.rss"
    params = {"q": query, "sort": "relevance", "t": "year", "limit": 25}

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        records = []

        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = entry.findtext(
                "{http://www.w3.org/2005/Atom}title", default=""
            )
            url = entry.findtext(
                "{http://www.w3.org/2005/Atom}link", default=""
            )
            if not url:
                link_node = entry.find("{http://www.w3.org/2005/Atom}link")
                if link_node is not None:
                    url = link_node.attrib.get("href", "")

            snippet = entry.findtext(
                "{http://www.w3.org/2005/Atom}content", default=""
            )
            date = entry.findtext(
                "{http://www.w3.org/2005/Atom}updated", default=""
            )

            record = make_record(
                title, url, snippet, "Reddit RSS", date, "discussion"
            )
            if record:
                records.append(record)
        return records, None
    except Exception as exc:
        return [], f"Reddit RSS: {type(exc).__name__}: {exc}"


def fetch_google_news(query):
    """Google News RSS search. Results are news context, not direct user proof."""
    endpoint = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}

    try:
        response = requests.get(
            endpoint, params=params, headers=HEADERS, timeout=TIMEOUT
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        records = []

        for item in root.findall(".//item")[:MAX_PER_QUERY]:
            title = item.findtext("title", default="")
            url = item.findtext("link", default="")
            snippet = item.findtext("description", default="")
            date = item.findtext("pubDate", default="")
            record = make_record(
                title, url, snippet, "Google News RSS", date, "news"
            )
            if record:
                records.append(record)
        return records, None
    except Exception as exc:
        return [], f"Google News: {type(exc).__name__}: {exc}"


def build_queries(topic):
    topic = topic.strip()

    if topic:
        return [
            f'"{topic}" problem OR difficulty',
            f'"{topic}" frustrated OR struggling',
        ]

    return [
        '"struggling with" OR "frustrated with"',
        '"I wish there was" OR "need a tool"',
        '"masalah" OR "kesulitan" OR "butuh solusi"',
    ]


def source_quality(record):
    """Filter known low-value pages and assign a source-type label."""
    url = record["url"]
    domain = record["domain"]
    kind = record["kind"]

    if not url or not domain:
        return False, "URL tidak valid"

    if "reddit.com" in domain:
        if is_reddit_root(url):
            return False, "Halaman komunitas, bukan postingan spesifik"
        if not is_specific_reddit_post(url):
            return False, "Bukan permalink postingan Reddit"
        record["kind"] = "discussion"
        return True, "Postingan diskusi"

    if domain.endswith("news.ycombinator.com"):
        if "item?id=" not in url:
            return False, "Bukan halaman diskusi spesifik"
        record["kind"] = "discussion"
        return True, "Diskusi atau tautan cerita"

    if kind == "news":
        return True, "Konteks berita, bukan bukti langsung kebutuhan"

    return True, "Sumber publik"


def analyze_record(record):
    text = f"{record['title']} {record['snippet']}".lower()

    pain = matches_any(text, PAIN_TERMS["difficulty"])
    repeated = matches_any(text, PAIN_TERMS["repeated_need"])
    workaround = matches_any(text, PAIN_TERMS["workaround"])
    payment = matches_any(text, PAIN_TERMS["payment"])
    solution = matches_any(text, PAIN_TERMS["solution_request"])
    counter = matches_any(text, PAIN_TERMS["counterevidence"])

    is_direct = record["kind"] == "discussion"

    # This is a transparent sorting heuristic, not a probability.
    score = 0
    score += min(len(pain) * 2, 6)
    score += min(len(repeated) * 2, 4)
    score += min(len(workaround) * 2, 4)
    score += min(len(payment) * 2, 4)
    score += min(len(solution), 2)
    score += 2 if is_direct else 0
    score -= min(len(counter) * 2, 4)
    score = max(0, min(20, score))

    signals = []
    if pain:
        signals.append("Indikasi keluhan")
    if repeated:
        signals.append("Indikasi masalah berulang")
    if workaround:
        signals.append("Indikasi solusi sementara")
    if payment:
        signals.append("Indikasi terkait biaya/pembayaran")
    if solution:
        signals.append("Permintaan bantuan/solusi")
    if counter:
        signals.append("Ada sinyal tandingan")

    if record["kind"] == "news":
        evidence_role = "Konteks industri, bukan bukti langsung kebutuhan"
    elif payment:
        evidence_role = "Diskusi dengan kata terkait biaya; belum tentu bukti pembayaran"
    elif pain:
        evidence_role = "Kandidat bukti masalah, perlu membaca konteks"
    else:
        evidence_role = "Konteks umum, relevansi belum kuat"

    record.update({
        "category": classify_category(text),
        "pain_terms": pain,
        "repeated_terms": repeated,
        "workaround_terms": workaround,
        "payment_terms": payment,
        "solution_terms": solution,
        "counter_terms": counter,
        "score": score,
        "signals": signals,
        "evidence_role": evidence_role,
        "is_direct_discussion": is_direct,
    })
    return record


def collect_research(topic, selected_sources):
    queries = build_queries(topic)
    all_records = []
    errors = []

    fetchers = {
        "GDELT News": fetch_gdelt,
        "Hacker News": fetch_hacker_news,
        "Reddit RSS": fetch_reddit,
        "Google News RSS": fetch_google_news,
    }

    total_calls = len(queries) * len(selected_sources)
    progress = st.progress(0, text="Memulai pengumpulan sumber...")
    completed = 0

    for query in queries:
        for source_name in selected_sources:
            records, error = fetchers[source_name](query)
            all_records.extend(records)
            if error:
                errors.append(error)

            completed += 1
            progress.progress(
                completed / max(total_calls, 1),
                text=f"Mengumpulkan data: {completed}/{total_calls}",
            )

    progress.empty()

    unique = {}
    for record in all_records:
        key = record["canonical_url"]
        if key and key not in unique:
            unique[key] = record

    accepted = []
    rejected = []

    for record in unique.values():
        ok, reason = source_quality(record)
        if ok:
            accepted.append(analyze_record(record))
        else:
            record["rejection_reason"] = reason
            rejected.append(record)

    accepted.sort(key=lambda x: x["score"], reverse=True)
    return accepted, rejected, errors, queries


def get_independent_domains(records):
    return len({
        r["domain"] for r in records
        if r.get("domain")
    })


def summarize_findings(records):
    if not records:
        return []

    categories = {}
    for record in records:
        category = record["category"]
        categories.setdefault(category, []).append(record)

    results = []
    for category, items in categories.items():
        discussions = [
            x for x in items if x["is_direct_discussion"]
        ]
        payment_signals = [
            x for x in items if x["payment_terms"]
        ]
        counter_signals = [
            x for x in items if x["counter_terms"]
        ]
        domains = get_independent_domains(discussions)

        if len(discussions) >= 5 and domains >= 3:
            evidence_status = "Pola awal lintas sumber"
        elif len(discussions) >= 2:
            evidence_status = "Indikasi awal"
        else:
            evidence_status = "Bukti langsung masih minim"

        results.append({
            "category": category,
            "total": len(items),
            "discussions": len(discussions),
            "domains": domains,
            "payment_signals": len(payment_signals),
            "counter_signals": len(counter_signals),
            "status": evidence_status,
            "items": items,
        })

    results.sort(
        key=lambda x: (
            x["discussions"],
            x["domains"],
            x["payment_signals"],
        ),
        reverse=True,
    )
    return results


# ------------------------- UI -----------------------------

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 Vanya Research Engine")
st.caption(
    "Mesin riset masalah manusia dan peluang. "
    "Berbasis bukti publik, bukan klaim otomatis."
)

with st.sidebar:
    st.header("Pengaturan riset")
    topic = st.text_input(
        "Topik khusus (opsional)",
        placeholder="Contoh: pembukuan UMKM, belajar matematika",
        help="Kosongkan untuk eksplorasi umum.",
    )

    selected_sources = st.multiselect(
        "Sumber yang digunakan",
        options=[
            "GDELT News",
            "Hacker News",
            "Reddit RSS",
            "Google News RSS",
        ],
        default=[
            "GDELT News",
            "Hacker News",
            "Reddit RSS",
            "Google News RSS",
        ],
    )

    st.caption(
        "Pencarian umum memakai beberapa frasa eksplorasi. "
        "Topik khusus akan memakai query terkait masalah."
    )

    run_search = st.button(
        "🚀 Mulai riset",
        type="primary",
        use_container_width=True,
    )

    st.divider()
    st.caption("Tidak ada database permanen. Data hasil riset disimpan dalam sesi aplikasi.")

if "research_results" not in st.session_state:
    st.session_state.research_results = None

if run_search:
    if not selected_sources:
        st.warning("Pilih minimal satu sumber.")
    else:
        with st.spinner("Vanya sedang mencari dan menyaring bukti..."):
            records, rejected, errors, queries = collect_research(
                topic, selected_sources
            )
            st.session_state.research_results = {
                "records": records,
                "rejected": rejected,
                "errors": errors,
                "queries": queries,
                "topic": topic,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

data = st.session_state.research_results

if data is None:
    st.info(
        "Atur sumber di panel kiri, lalu tekan **Mulai riset**. "
        "Untuk riset yang lebih terarah, masukkan topik khusus."
    )
    st.subheader("Apa yang akan diperiksa?")
    st.markdown(
        "- Kandidat keluhan dan permintaan bantuan\n"
        "- Masalah berulang dan solusi sementara\n"
        "- Sinyal terkait biaya atau pembayaran\n"
        "- Bukti tandingan dan sumber yang kurang relevan\n"
        "- Tautan asli agar setiap temuan bisa diperiksa"
    )
    st.stop()

records = data["records"]
rejected = data["rejected"]
errors = data["errors"]
summaries = summarize_findings(records)

st.caption(
    f"Topik: {data['topic'] or 'Eksplorasi umum'} · "
    f"Terakhir dijalankan: {data['timestamp']}"
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Sumber unik lolos filter", len(records))
m2.metric(
    "Diskusi spesifik",
    sum(1 for r in records if r["is_direct_discussion"]),
)
m3.metric(
    "Sumber/domain independen",
    get_independent_domains(records),
)
m4.metric("Halaman ditolak", len(rejected))

st.warning(
    "Skor adalah heuristik penyaringan, bukan probabilitas kebutuhan, "
    "bukan validasi pasar, dan bukan bukti seseorang mau membayar."
)

tab1, tab2, tab3, tab4 = st.tabs([
    "📡 Opportunity Radar",
    "🧾 Evidence Explorer",
    "🧩 Analisis kategori",
    "🚧 Batas & error",
])

with tab1:
    st.subheader("Kandidat masalah untuk diteliti")
    if not records:
        st.warning(
            "Tidak ada hasil yang lolos filter. "
            "Coba topik lain atau gunakan sumber berbeda."
        )
    else:
        categories = ["Semua"] + sorted({
            r["category"] for r in records
        })
        chosen_category = st.selectbox(
            "Filter kategori", categories
        )
        min_score = st.slider(
            "Skor minimum untuk ditampilkan",
            min_value=0,
            max_value=20,
            value=2,
        )

        filtered = [
            r for r in records
            if r["score"] >= min_score
            and (
                chosen_category == "Semua"
                or r["category"] == chosen_category
            )
        ]

        st.caption(f"{len(filtered)} hasil cocok dengan filter.")

        for index, record in enumerate(filtered):
            with st.container(border=True):
                st.markdown(f"**{record['title']}**")
                st.caption(
                    f"{record['source']} · {record['domain']} · "
                    f"{record['category']}"
                )
                st.write(record["evidence_role"])

                left, right = st.columns([3, 1])
                with left:
                    if record["signals"]:
                        st.write("Sinyal: " + ", ".join(record["signals"]))
                    else:
                        st.write("Sinyal masalah belum kuat.")
                with right:
                    st.metric("Skor filter", record["score"], "/ 20")

                if record["snippet"]:
                    st.write(record["snippet"][:500])

                st.link_button(
                    "Buka sumber asli",
                    record["url"],
                    use_container_width=False,
                )

                with st.expander("Lihat alasan penilaian"):
                    st.write("Kata terkait masalah:", record["pain_terms"])
                    st.write("Masalah berulang:", record["repeated_terms"])
                    st.write("Solusi sementara:", record["workaround_terms"])
                    st.write("Kata terkait pembayaran:", record["payment_terms"])
                    st.write("Permintaan solusi:", record["solution_terms"])
                    st.write("Sinyal tandingan:", record["counter_terms"])

with tab2:
    st.subheader("Bukti dan tautan sumber")
    if records:
        source_filter = st.multiselect(
            "Filter sumber",
            options=sorted({r["source"] for r in records}),
            default=sorted({r["source"] for r in records}),
        )

        for record in records:
            if record["source"] not in source_filter:
                continue

            st.markdown(f"**{record['title']}**")
            st.caption(
                f"{record['source']} · {record['domain']} · "
                f"{record['date'] or 'Tanggal tidak tersedia'}"
            )
            st.write(record["snippet"] or "Tidak ada ringkasan yang tersedia.")
            st.write(f"Peran bukti: {record['evidence_role']}")
            st.markdown(f"[Buka sumber]({record['url']})")
            st.divider()
    else:
        st.info("Belum ada bukti untuk ditampilkan.")

with tab3:
    st.subheader("Ringkasan pola, bukan kesimpulan final")
    if summaries:
        for item in summaries:
            with st.container(border=True):
                st.markdown(f"**{item['category']}**")
                st.write(f"Status: **{item['status']}**")
                a, b, c, d = st.columns(4)
                a.metric("Semua hasil", item["total"])
                b.metric("Diskusi spesifik", item["discussions"])
                c.metric("Domain diskusi", item["domains"])
                d.metric("Sinyal pembayaran", item["payment_signals"])

                st.write(
                    f"Bukti tandingan terdeteksi pada "
                    f"{item['counter_signals']} hasil."
                )
                st.caption(
                    "Kategori berasal dari kata kunci. "
                    "Hasil dalam satu kategori belum tentu membahas "
                    "masalah yang sama."
                )
    else:
        st.info("Belum ada pola yang dapat diringkas.")

with tab4:
    st.subheader("Hal yang perlu diketahui")
    st.markdown(
        "- Sumber yang gagal diakses tidak berarti masalahnya tidak ada.\n"
        "- Berita bukan bukti langsung bahwa pelanggan mengalami masalah.\n"
        "- Kata terkait harga bukan bukti seseorang benar-benar membayar.\n"
        "- Hasil pencarian dapat berulang, bias, atau tidak relevan.\n"
        "- Kategori saat ini berbasis kata kunci, belum menggunakan "
        "pemahaman semantik.\n"
        "- Sistem tidak membaca seluruh isi setiap halaman; ringkasan "
        "dapat tidak lengkap.\n"
        "- Tidak semua komunitas, situs login, atau sumber privat dapat "
        "diakses.\n"
        "- Jangan mengumpulkan atau menyimpulkan informasi sensitif "
        "tentang individu. Fokus pada pola masalah yang bersifat umum."
    )

    st.write("**Query yang digunakan:**")
    for query in data["queries"]:
        st.code(query)

    st.write("**Halaman yang ditolak oleh filter:**")
    if rejected:
        for item in rejected[:50]:
            st.write(
                f"- {item['title']} | {item.get('rejection_reason', '')}"
            )
            st.caption(item["url"])
    else:
        st.write("Tidak ada halaman yang ditolak.")

    st.write("**Sumber yang mengalami error:**")
    if errors:
        for error in errors:
            st.error(error)
    else:
        st.success("Tidak ada error yang dilaporkan pada pengambilan data ini.")

st.divider()
st.caption(
    "Vanya Research Engine v1 · Hasil bersifat eksploratif. "
    "Validasi kebutuhan membutuhkan pemeriksaan konteks dan, bila sesuai, "
    "riset langsung dengan calon pengguna."
)
