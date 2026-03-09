"""
Mikroservis iletişimi: FastAPI transcript API'ye istek atar.
"""
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

from django.conf import settings

# FastAPI transcript API base URL (settings'den veya varsayılan)
TRANSCRIPT_API_BASE = getattr(
    settings, "TRANSCRIPT_MICROSERVICE_URL", "http://127.0.0.1:8000"
).rstrip("/")
TRANSCRIPT_TIMEOUT = getattr(settings, "TRANSCRIPT_MICROSERVICE_TIMEOUT", 15)


def extract_video_id_from_url(youtube_url: str) -> Optional[str]:
    """
    YouTube URL'den video_id çıkarır.
    watch?v= ve youtu.be/ formatlarını destekler.
    """
    if not youtube_url or not youtube_url.strip():
        return None
    url = youtube_url.strip()
    # youtu.be/ID
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)
    # youtube.com/watch?v=ID
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc and parsed.path in ("/watch", "/watch/"):
        qs = parse_qs(parsed.query)
        vid = (qs.get("v") or [None])[0]
        if vid and re.match(r"^[a-zA-Z0-9_-]{11}$", vid):
            return vid
    # Genel ?v= araması
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)
    return None


class TranscriptServiceError(Exception):
    """Transkript mikroservisi hatası."""
    pass


def fetch_transcript_from_microservice(youtube_url: str) -> dict:
    """
    Verilen YouTube URL için FastAPI transcript mikroservisine GET isteği atar.
    video_id URL'den çıkarılır (watch?v= ve youtu.be/ desteklenir).
    Başarılı yanıtta (status 200 ve JSON'da status=='ok') sözlük döner.
    Hata durumunda TranscriptServiceError fırlatır.
    """
    video_id = extract_video_id_from_url(youtube_url)
    if not video_id:
        raise TranscriptServiceError("Geçerli bir YouTube URL gerekli (video_id çıkarılamadı).")

    url = f"{TRANSCRIPT_API_BASE}/transcript"
    params = {"video_id": video_id, "clean": "true"}

    try:
        response = requests.get(url, params=params, timeout=TRANSCRIPT_TIMEOUT)
    except requests.exceptions.Timeout:
        raise TranscriptServiceError(
            f"Transkript servisi {TRANSCRIPT_TIMEOUT} saniye içinde yanıt vermedi."
        )
    except requests.exceptions.RequestException as e:
        raise TranscriptServiceError(f"Transkript servisine bağlanılamadı: {e}")

    try:
        data = response.json()
    except ValueError:
        raise TranscriptServiceError("Servis geçersiz JSON döndü.")

    if response.status_code != 200:
        detail = data.get("detail", response.text) if isinstance(data, dict) else response.text
        raise TranscriptServiceError(f"Servis hatası ({response.status_code}): {detail}")

    if data.get("status") != "ok":
        raise TranscriptServiceError(data.get("detail", "Transkript alınamadı."))

    return data
