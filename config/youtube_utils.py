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


def _fetch_via_api(video_id: str) -> tuple[list, Optional[str]]:
    """youtube-transcript-api ile dener (fallback)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import YouTubeTranscriptApiException
        from youtube_transcript_api.proxies import GenericProxyConfig
    except ImportError:
        return [], "Transkript servisi yapılandırılmamış."

    proxy_config = None
    http_p = getattr(settings, "YOUTUBE_HTTP_PROXY", None) or None
    https_p = getattr(settings, "YOUTUBE_HTTPS_PROXY", None) or None
    single_p = getattr(settings, "YOUTUBE_PROXY", None) or None
    if single_p:
        http_p = http_p or single_p
        https_p = https_p or single_p
    if http_p or https_p:
        try:
            proxy_config = GenericProxyConfig(http_url=http_p, https_url=https_p)
        except Exception:
            proxy_config = None
    try:
        api = YouTubeTranscriptApi(proxy_config=proxy_config)
        fetched = api.fetch(video_id, languages=("tr", "en"))
        return [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in fetched.snippets
        ], None
    except YouTubeTranscriptApiException as e:
        return [], str(e)
    except Exception as e:
        return [], f"Transkript alınamadı: {e}"


def get_transcript_for_video(video_id: str) -> tuple[list, Optional[str]]:
    """
    Video ID için transkript döner. Önce cache, sonra ScrapingBee -> browser (Playwright) -> API.
    Returns: (segments, error_message)
    """
    prefix = getattr(settings, "TRANSCRIPT_CACHE_KEY_PREFIX", "yt_transcript:")
    timeout = getattr(settings, "TRANSCRIPT_CACHE_TIMEOUT", 3600)
    cache_key = f"{prefix}{video_id}"

    cached = cache.get(cache_key)
    if cached is not None:
        return cached, None

    result, error = [], None

    # 1) ScrapingBee (API key varsa, engelden kaçınma için öncelikli)
    use_scrapingbee = getattr(settings, "TRANSCRIPT_USE_SCRAPINGBEE", True)
    if use_scrapingbee and (getattr(settings, "SCRAPINGBEE_API_KEY", None) or "").strip():
        try:
            from config.transcript_scrapingbee import fetch_transcript_scrapingbee
            result, error = fetch_transcript_scrapingbee(video_id)
        except Exception as e:
            error = str(e)

    # 2) Playwright browser scraper
    if not result and error:
        use_browser = getattr(settings, "TRANSCRIPT_USE_BROWSER_SCRAPER", True)
        if use_browser:
            try:
                from config.transcript_scraper import fetch_transcript_browser
                result, error = fetch_transcript_browser(video_id)
            except Exception as e:
                error = str(e)

    # 3) youtube-transcript-api fallback
    if not result and error:
        result, error = _fetch_via_api(video_id)

    if result:
        cache.set(cache_key, result, timeout=timeout)
        return result, None
    return [], error or "Transkript alınamadı."
