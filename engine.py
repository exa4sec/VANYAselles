
import os
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import feedparser
import pandas as pd
import requests

DB_PATH = Path(os.getenv("VANYA_DB_PATH", "vanya.db"))

PLATFORMS = [
    "TikTok",
    "Instagram Reels",
    "YouTube Shorts",
    "YouTube Long-form",
    "Instagram Carousel",
]

TREND_URL = (
    "https://trends.google.com/trending/rss?geo=ID"
)

NEWS_URL = (
    "https://news.google.com/rss/search?"
    "q={query}&hl=id&gl=ID&ceid=ID:id"
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS trend_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT,
                topic TEXT,
                score REAL,
                traffic TEXT
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT,
                topic TEXT,
                platform TEXT,
                views INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                comments INTEGER DEFAULT 0,
                shares INTEGER DEFAULT 0,
                followers INTEGER DEFAULT 0,
                revenue REAL DEFAULT 0,
                post_url TEXT DEFAULT ''
            )
        """)
        con.commit()


def parse_traffic(value):
    if not value:
        return 0

    match = re.search(
        r"([\d,.]+)\s*([KMB]?)",
        str(value).upper().replace(",", "")
    )

    if not match:
        return 0

    number = float(match.group(1))
    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }[match.group(2)]

    return int(number * multiplier)


def fetch_trends(limit=25):
    response = requests.get(
        TREND_URL,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    results = []

    for entry in feed.entries[:limit]:
        topic = entry.get("title", "").strip()

        if not topic:
            continue

        traffic = entry.get("ht_approx_traffic", "")

        # Metadata berita dari Google Trends, jika tersedia.
        news_titles = []
        news_items = entry.get("ht_news_item", [])

        if isinstance(news_items, dict):
            news_items = [news_items]

        for item in news_items:
            if isinstance(item, dict):
                title = item.get("ht_news_item_title", "")
                if title:
                    news_titles.append(title)

        results.append({
            "topic": topic,
            "traffic": traffic,
            "traffic_estimate": parse_traffic(traffic),
            "news_count": len(news_titles),
            "news_titles": news_titles,
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
        })

    if not results:
        raise RuntimeError(
            "Feed tren kosong. Coba lagi atau periksa sumber RSS."
        )

    return results


def fetch_news(topic, limit=5):
    url = NEWS_URL.format(query=quote(topic))

    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except requests.RequestException:
        return []

    return [
        {
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "published": item.get("published", ""),
        }
        for item in feed.entries[:limit]
    ]


def analyze_trends(trends):
    df = pd.DataFrame(trends)

    if df.empty:
        return df

    df["traffic_estimate"] = pd.to_numeric(
        df["traffic_estimate"], errors="coerce"
    ).fillna(0)

    df["news_count"] = pd.to_numeric(
        df["news_count"], errors="coerce"
    ).fillna(0)

    # Ranking relatif terhadap hasil pencarian saat ini.
    df["traffic_score"] = (
        df["traffic_estimate"].rank(pct=True) * 100
    )

    df["coverage_score"] = (
        df["news_count"].rank(pct=True) * 100
    )

    commercial_words = [
        "harga", "review", "terbaik", "rekomendasi",
        "ai", "aplikasi", "bisnis", "usaha",
        "belajar", "tutorial", "produk", "laptop",
        "ponsel", "karier", "kerja",
    ]

    def commercial_score(topic):
        topic = str(topic).lower()
        return (
            100
            if any(word in topic for word in commercial_words)
            else 35
        )

    df["commercial_score"] = df["topic"].apply(
        commercial_score
    )

    df["opportunity_score"] = (
        df["traffic_score"] * 0.45
        + df["coverage_score"] * 0.30
        + df["commercial_score"] * 0.25
    ).round(1)

    return df.sort_values(
        "opportunity_score", ascending=False
    ).reset_index(drop=True)


def save_trends(df):
    init_db()

    with sqlite3.connect(DB_PATH) as con:
        for _, row in df.iterrows():
            con.execute("""
                INSERT INTO trend_history
                (captured_at, topic, score, traffic)
                VALUES (?, ?, ?, ?)
            """, (
                timestamp(),
                str(row["topic"]),
                float(row["opportunity_score"]),
                str(row["traffic"]),
            ))
        con.commit()


def fallback_draft(topic, platform, news):
    context = "; ".join(
        item["title"] for item in news[:3]
    )

    if platform == "Instagram Carousel":
        script = (
            f"Slide 1: {topic}, apa yang perlu diketahui?\n"
            "Slide 2: Konteks dan latar belakang\n"
            "Slide 3: Tiga poin utama\n"
            "Slide 4: Dampak untuk audiens\n"
            "Slide 5: Kesimpulan dan pertanyaan"
        )
    else:
        script = (
            f"HOOK: Lagi ramai soal {topic}. Apa konteksnya?\n\n"
            "ISI: Jelaskan latar belakang, tiga poin penting, "
            "dan manfaat praktis bagi audiens.\n\n"
            "PENUTUP: Rangkum inti pembahasan dan ajak audiens "
            "berdiskusi."
        )

    return {
        "angle": f"Penjelasan praktis tentang {topic}",
        "hook": f"Lagi ramai soal {topic}. Ini konteksnya.",
        "script": script,
        "caption": (
            f"Yuk pahami {topic} sebelum ikut menyebarkan. "
            "#Edukasi #Trending"
        ),
        "cta": "Apa pendapatmu? Tulis di komentar.",
        "monetization": (
            "Pertimbangkan afiliasi, sponsor, atau produk "
            "relevan hanya jika benar-benar bermanfaat."
        ),
        "verification": (
            "Verifikasi fakta dengan sumber primer. "
            f"Judul berita terkait: {context or 'belum tersedia'}"
        ),
    }


def generate_draft(topic, platform, niche, news, api_key, model):
    if not api_key:
        return fallback_draft(topic, platform, news)

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    news_context = "\n".join(
        f"- {item['title']} | {item['link']}"
        for item in news
    )

    prompt = f"""
Buat draft konten orisinal berbahasa Indonesia.

Topik: {topic}
Niche: {niche}
Platform: {platform}
Tujuan: pertumbuhan audiens dan monetisasi jangka panjang.

Judul berita RSS untuk konteks, bukan bukti kebenaran:
{news_context or "Tidak tersedia"}

Aturan:
- Hook kuat tetapi tidak menyesatkan.
- Sesuaikan format dengan platform.
- Jangan mengarang angka, kutipan, atau fakta.
- Bedakan fakta, opini, dan hal yang perlu diverifikasi.
- Jangan menjanjikan hasil finansial.
- Jangan menyalin karya kreator lain.
- Ide monetisasi harus relevan dan transparan.
- Jangan menyatakan konten pasti viral.

Kembalikan JSON dengan field:
angle, hook, script, caption, cta, monetization, verification.
Semua nilai berupa string.
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Kamu adalah content strategist dan editor "
                    "yang kritis, kreatif, serta faktual."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("AI mengembalikan respons kosong.")

    return json.loads(content)


def log_performance(
    topic, platform, views, likes, comments, shares,
    followers, revenue, post_url=""
):
    init_db()

    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO performance
            (recorded_at, topic, platform, views, likes,
             comments, shares, followers, revenue, post_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp(), topic, platform, views, likes,
            comments, shares, followers, revenue, post_url,
        ))
        con.commit()


def get_performance():
    init_db()

    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query(
            "SELECT * FROM performance ORDER BY id DESC",
            con,
        )


def get_trend_history():
    init_db()

    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query(
            "SELECT * FROM trend_history ORDER BY id DESC",
            con,
        )
