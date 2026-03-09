#!/usr/bin/env python3
"""
FastAPI uygulaması: YouTube transkript API.
fetch_transcript.py ve utils/cleaner.py kullanır.
"""
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

# Proje kökünü path'e ekle
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware

# Rate limiting: IP başına son N istek zamanları (dakika)
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SEC = 60
request_times: dict[str, deque] = {}


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str) -> bool:
    """IP için rate limit kontrolü. True = izin ver, False = reddet."""
    now = time.time()
    if ip not in request_times:
        request_times[ip] = deque(maxlen=RATE_LIMIT_REQUESTS)
    times = request_times[ip]
    # Eski kayıtları temizle
    while times and now - times[0] > RATE_LIMIT_WINDOW_SEC:
        times.popleft()
    if len(times) >= RATE_LIMIT_REQUESTS:
        return False
    times.append(now)
    return True


app = FastAPI(
    title="YouTube Transcript API",
    description="YouTube video transkriptini çeker ve temizler",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production: ["https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "message": "YouTube Transcript API", "docs": "/docs"}


@app.get("/transcript")
async def get_transcript(
    request: Request,
    video_id: Optional[str] = None,
    video_url: Optional[str] = None,
    clean: bool = True,
    languages: str = "tr,en",
):
    """
    YouTube video transkriptini döner.
    video_id veya video_url parametrelerinden biri zorunludur.
    """
    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit aşıldı. Dakikada en fazla {RATE_LIMIT_REQUESTS} istek.",
        )

    # ID çıkar
    from scripts.fetch_transcript import fetch_transcript, _extract_video_id

    vid = None
    if video_id:
        vid = _extract_video_id(video_id)
    if not vid and video_url:
        vid = _extract_video_id(video_url)

    if not vid:
        raise HTTPException(
            status_code=400,
            detail="Geçersiz video_id veya video_url. Lütfen video_id veya video_url parametresi verin.",
        )

    # Transkript çek
    try:
        segments, error = fetch_transcript(
            vid,
            cookies_path=str(ROOT / "cookies.txt") if (ROOT / "cookies.txt").is_file() else None,
            languages=tuple(l.strip() for l in languages.split(",") if l.strip()) or ("tr", "en"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {str(e)}")

    if error:
        err_lower = error.lower()
        if "bulunamadı" in err_lower or "mevcut değil" in err_lower or "silinmiş" in err_lower:
            raise HTTPException(status_code=404, detail=error)
        if "ip" in err_lower or "blocked" in err_lower or "engel" in err_lower or "429" in err_lower:
            raise HTTPException(status_code=429, detail=error)
        if "transkript" in err_lower and "kapalı" in err_lower:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=500, detail=error)

    raw_text = " ".join(s.get("text", "") for s in segments if s.get("text")).strip()

    # Opsiyonel: video başlığı (yt-dlp ile)
    title = None
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            title = info.get("title") if info else None
    except Exception:
        pass

    clean_text = raw_text
    if clean and raw_text:
        from utils.cleaner import clean_transcript
        clean_text = clean_transcript(
            segments,
            remove_sound_effects_flag=True,
            deduplicate_words=True,
            split_paragraphs=False,
        )

    return {
        "status": "ok",
        "video_id": vid,
        "title": title,
        "raw_text": raw_text,
        "clean_text": clean_text,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
