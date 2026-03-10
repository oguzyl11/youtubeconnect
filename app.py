#!/usr/bin/env python3
"""
FastAPI transcript API. .env'den YOUTUBE_PROXY_LIST okunur; proxy rotation ile transkript çekilir.
"""
import os
import sys
from pathlib import Path

# .env yükle (uygulama başlamadan önce)
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="YouTube Transcript API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "message": "YouTube Transcript API", "docs": "/docs"}


@app.get("/transcript")
async def get_transcript(
    video_id: str = None,
    video_url: str = None,
    clean: bool = True,
    languages: str = "tr,en",
):
    """YouTube video transkriptini döner. video_id veya video_url zorunlu."""
    from scripts.fetch_transcript import fetch_transcript, _extract_video_id

    vid = None
    if video_id:
        vid = _extract_video_id(video_id)
    if not vid and video_url:
        vid = _extract_video_id(video_url)

    if not vid:
        raise HTTPException(
            status_code=400,
            detail="Geçersiz video_id veya video_url.",
        )

    raw_list = (os.getenv("YOUTUBE_PROXY_LIST") or "").strip()
    proxy_list = [p.strip() for p in raw_list.split(",") if p.strip()] if raw_list else []
    cookies_path = str(ROOT / "cookies.txt") if (ROOT / "cookies.txt").is_file() else None
    lang_tuple = tuple(l.strip() for l in languages.split(",") if l.strip()) or ("tr", "en")

    segments, error = fetch_transcript(
        vid,
        cookies_path=cookies_path,
        languages=lang_tuple,
        use_ytdlp_fallback=True,
        proxy_list=proxy_list,
    )

    if error:
        err_lower = (error or "").lower()
        if "bulunamadı" in err_lower or "mevcut değil" in err_lower:
            raise HTTPException(status_code=404, detail=error)
        if "ip" in err_lower or "blocked" in err_lower or "engel" in err_lower:
            raise HTTPException(status_code=429, detail=error)
        raise HTTPException(status_code=500, detail=error)

    raw_text = " ".join(s.get("text", "") for s in segments if s.get("text")).strip()
    clean_text = raw_text

    if clean and raw_text:
        try:
            from utils.cleaner import clean_transcript
            clean_text = clean_transcript(
                segments,
                remove_sound_effects_flag=True,
                deduplicate_words=True,
                split_paragraphs=False,
            )
        except ImportError:
            pass

    title = None
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            title = info.get("title") if info else None
    except Exception:
        pass

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
