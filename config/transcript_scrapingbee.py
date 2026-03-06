"""
ScrapingBee API ile YouTube transkript çekme – proxy + JS rendering, engelden kaçınma.
"""
import json
import re
from typing import Optional, Tuple

from django.conf import settings


def _parse_ts_to_seconds(ts_text: str) -> float:
    """'1:23' veya '12:34' formatını saniyeye çevirir."""
    if not ts_text or not ts_text.strip():
        return 0.0
    parts = re.findall(r"\d+", ts_text.strip())
    if len(parts) >= 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 1:
        return int(parts[0])
    return 0.0


def fetch_transcript_scrapingbee(video_id: str) -> Tuple[list, Optional[str]]:
    """
    ScrapingBee ile YouTube sayfasını açıp transkript panelini tıklayıp HTML'den parse eder.
    Returns: (segments, error_message)
    """
    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None) or None
    if not api_key or not api_key.strip():
        return [], "SCRAPINGBEE_API_KEY ayarlanmamış."

    url = f"https://www.youtube.com/watch?v={video_id}"

    # Transkript butonunu aç, segmentleri bekle
    js_scenario = {
        "instructions": [
            {"wait": 2000},
            {"wait_for_and_click": "ytd-video-description-transcript-section-renderer button"},
            {"wait": 2500},
            {"wait_for": "#segments-container"},
        ],
        "strict": False,
    }

    try:
        from scrapingbee import ScrapingBeeClient
    except ImportError:
        return [], "scrapingbee yüklü değil: pip install scrapingbee"

    try:
        client = ScrapingBeeClient(api_key=api_key.strip())
        response = client.get(
            url,
            params={
                "render_js": True,
                "js_scenario": json.dumps(js_scenario),
                "timeout": 40000,
            },
        )
    except Exception as e:
        return [], f"ScrapingBee istek hatası: {e}"

    if response.status_code != 200:
        return [], f"ScrapingBee HTTP {response.status_code}"

    html = response.content
    if not html:
        return [], "ScrapingBee boş yanıt döndü."

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], "beautifulsoup4 yüklü değil: pip install beautifulsoup4"

    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#segments-container")
    if not container:
        return [], "Transkript alanı bulunamadı (video altyazı desteklemiyor olabilir)."

    segments_raw = []
    for seg in container.select("ytd-transcript-segment-renderer"):
        text_el = seg.select_one("yt-formatted-string.segment-text")
        time_el = seg.select_one("span[aria-label]")
        text = (text_el.get_text(strip=True) if text_el else "").strip()
        if not text:
            continue
        start = 0.0
        if time_el and time_el.get("aria-label"):
            start = _parse_ts_to_seconds(time_el["aria-label"])
        segments_raw.append({"text": text, "start": start})

    if not segments_raw:
        for i, el in enumerate(container.select("yt-formatted-string")):
            text = el.get_text(strip=True)
            if text:
                segments_raw.append({"text": text, "start": i * 5.0})

    if not segments_raw:
        return [], "Bu video için altyazı bulunamadı."

    result = []
    for i, item in enumerate(segments_raw):
        start = float(item.get("start") or 0)
        next_start = segments_raw[i + 1].get("start") if i + 1 < len(segments_raw) else start + 5
        duration = max(0.1, next_start - start) if isinstance(next_start, (int, float)) else 5.0
        result.append({"text": item["text"], "start": start, "duration": duration})

    return result, None
