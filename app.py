
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(
    title="Vanya Stock Intelligence",
    version="1.0.0",
    description="BEI market dashboard without a database",
)

# Batasi origin sesuai lokasi frontend kamu.
origins = [
    x.strip()
    for x in os.getenv(
        "VANYA_CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500"
    ).split(",")
    if x.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

MARKET_URL = os.getenv("MARKET_DATA_BASE_URL", "").rstrip("/")
MARKET_KEY = os.getenv("MARKET_DATA_API_KEY", "")

AI_URL = os.getenv("AI_API_URL", "").rstrip("/")
AI_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def require_market_provider():
    if not MARKET_URL:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "provider_not_configured",
                "message": (
                    "Sumber data saham belum dikonfigurasi. "
                    "Hubungkan penyedia data yang sah terlebih dahulu."
                ),
            },
        )


async def market_get(path: str, params: dict | None = None) -> Any:
    """Mengambil data langsung dari provider, tanpa menyimpannya."""
    require_market_provider()

    headers = {"Accept": "application/json"}
    if MARKET_KEY:
        headers["Authorization"] = f"Bearer {MARKET_KEY}"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{MARKET_URL}/{path.lstrip('/')}",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Provider data gagal: HTTP {exc.response.status_code}",
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Provider data tidak dapat dihubungi.",
        )
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="Provider tidak mengembalikan JSON yang valid.",
        )


@app.get("/")
def home():
    return {
        "app": "Vanya Stock Intelligence",
        "status": "running",
        "database": False,
        "market_provider_configured": bool(MARKET_URL),
        "ai_configured": bool(AI_URL and AI_KEY and AI_MODEL),
        "timestamp_utc": now_utc(),
    }


@app.get("/api/status")
def status():
    return {
        "database": "disabled",
        "market_data": (
            "provider_configured" if MARKET_URL
            else "not_configured"
        ),
        "ai": (
            "configured" if AI_URL and AI_KEY and AI_MODEL
            else "not_configured"
        ),
        "checked_at_utc": now_utc(),
        "warning": (
            "Konfigurasi provider tidak otomatis berarti "
            "akses real-time sudah tersedia."
        ),
    }


@app.get("/api/instruments")
async def instruments(
    q: str = "",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    # Kontrak adapter Vanya, bukan endpoint resmi BEI.
    data = await market_get(
        "instruments",
        {"q": q, "limit": limit, "offset": offset},
    )

    return {
        "data": data,
        "source": "configured_provider",
        "retrieved_at_utc": now_utc(),
    }


@app.get("/api/quote/{ticker}")
async def quote(ticker: str):
    symbol = ticker.strip().upper()

    if not symbol:
        raise HTTPException(400, "Kode saham wajib diisi.")

    data = await market_get(f"quote/{symbol}")

    return {
        "ticker": symbol,
        "data": data,
        "source": "configured_provider",
        "retrieved_at_utc": now_utc(),
        "note": (
            "Gunakan timestamp dan metadata provider untuk "
            "memastikan apakah data real-time atau tertunda."
        ),
    }


@app.get("/api/history/{ticker}")
async def history(
    ticker: str,
    start: str,
    end: str,
    interval: str = Query(
        "1d",
        pattern="^(1d|1m|5m|15m|30m|1h)$",
    ),
):
    # Validasi tanggal sebelum mengirim permintaan.
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            422, "Tanggal harus menggunakan format YYYY-MM-DD."
        )

    if start_date > end_date:
        raise HTTPException(
            422, "Tanggal awal tidak boleh setelah tanggal akhir."
        )

    symbol = ticker.strip().upper()

    data = await market_get(
        f"history/{symbol}",
        {
            "start": start,
            "end": end,
            "interval": interval,
        },
    )

    return {
        "ticker": symbol,
        "data": data,
        "source": "configured_provider",
        "retrieved_at_utc": now_utc(),
        "interval": interval,
    }


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=3000)
    market_data: dict[str, Any]


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    if not (AI_URL and AI_KEY and AI_MODEL):
        raise HTTPException(
            503,
            "AI belum dikonfigurasi. Periksa variabel AI_API_URL, "
            "AI_API_KEY, dan AI_MODEL.",
        )

    system_prompt = """
Kamu adalah Vanya Stock Intelligence, asisten riset saham Indonesia.

ATURAN:
1. Gunakan hanya data yang diberikan pengguna.
2. Jangan pernah mengarang harga, volume, tanggal, berita,
   laporan keuangan, atau sumber.
3. Pisahkan fakta teramati, hasil perhitungan, dan interpretasi.
4. Jika data tidak lengkap atau kedaluwarsa, katakan dengan jelas.
5. Jangan menjanjikan keuntungan atau menyebut prediksi sebagai fakta.
6. Cantumkan keterbatasan analisis dan timestamp jika tersedia.
7. Jawab dalam bahasa Indonesia yang jelas dan terstruktur.
"""

    payload = {
        "model": AI_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Pertanyaan: {req.question}\n\n"
                    "Data pasar yang tersedia:\n"
                    f"{req.model_dump()['market_data']}"
                ),
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                AI_URL,
                headers={
                    "Authorization": f"Bearer {AI_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502,
            f"Provider AI gagal: HTTP {exc.response.status_code}",
        )
    except httpx.RequestError:
        raise HTTPException(502, "Provider AI tidak dapat dihubungi.")
    except ValueError:
        raise HTTPException(502, "Respons AI bukan JSON yang valid.")

    try:
        answer = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(
            502,
            "Format respons AI tidak sesuai dengan API kompatibel OpenAI.",
        )

    return {
        "answer": answer,
        "generated_at_utc": now_utc(),
        "data_persistence": "disabled",
        "disclaimer": (
            "Analisis berdasarkan data yang diberikan, bukan jaminan "
            "hasil investasi."
        ),
    }
