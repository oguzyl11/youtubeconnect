"""
YouTube URL ve transkript yardımcıları.
Ban riskini azaltmak: cache + rate limit (views içinde).
"""
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.cache import cache


def extract_youtube_video_id(url: str) -> Optional[str]:
    """YouTube URL'den video ID çıkarır. Desteklenen formatlar:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    """
    if not url or not url.strip():
        return None
    url = url.strip()
    # youtu.be/ID
    m = re.match(r"^(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})(?:\?.*)?$", url)
    if m:
        return m.group(1)
    # youtube.com/embed/ID
    m = re.match(
        r"^(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})(?:\?.*)?$",
        url,
    )
    if m:
        return m.group(1)
    # youtube.com/watch?v=ID
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc and parsed.path in ("/watch", "/watch/"):
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [None])[0]
        if vid and re.match(r"^[a-zA-Z0-9_-]{11}$", vid):
            return vid
    return None


def get_transcript_for_video(video_id: str) -> tuple[list, Optional[str]]:
    """
    Video ID için transkript döner.
    Yöntem: YouTube watch sayfasından ytInitialPlayerResponse çıkarılıp
    timedtext API (baseUrl) ile altyazı indirilir. API anahtarı gerekmez.
    Returns: (segments, error_message)
    """
    prefix = getattr(settings, "TRANSCRIPT_CACHE_KEY_PREFIX", "yt_transcript:")
    timeout = getattr(settings, "TRANSCRIPT_CACHE_TIMEOUT", 3600)
    cache_key = f"{prefix}{video_id}"

    cached = cache.get(cache_key)
    if cached is not None:
        return cached, None

    try:
        from config.transcript_timedtext import fetch_transcript_timedtext
        result, error = fetch_transcript_timedtext(video_id)
    except Exception as e:
        return [], str(e)

    if result:
        cache.set(cache_key, result, timeout=timeout)
        return result, None
    return [], error or "Transkript alınamadı."
