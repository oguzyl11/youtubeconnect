"""
ScrapingBee API ile YouTube transkript çekme – önce ucuz HTML + caption track,
gerekirse JS rendering ile panel açma (dokümantasyona uygun hibrit yapı).
"""
import json
import re
import xml.etree.ElementTree as ET
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


def _scrapingbee_base_params() -> dict:
    """Tüm ScrapingBee isteklerinde kullanılacak ortak parametreler (settings'den)."""
    params = {
        "timeout": getattr(settings, "SCRAPINGBEE_TIMEOUT", 60000),
    }
    if getattr(settings, "SCRAPINGBEE_PREMIUM_PROXY", False):
        params["premium_proxy"] = True
    return params


def _extract_caption_base_url(html: bytes) -> Optional[str]:
    """Sayfa HTML'inde captionTracks baseUrl (timedtext) arar, bulursa URL döner."""
    try:
        text = html.decode("utf-8", errors="ignore")
    except Exception:
        return None
    base_url_match = re.search(
        r'"baseUrl"\s*:\s*"((?:https?:)?[^"]+timedtext[^"]*)"',
        text,
    )
    if not base_url_match:
        base_url_match = re.search(
            r'baseUrl["\s:]+"(https?[^"]+)"',
            text,
        )
    if not base_url_match:
        return None
    caption_url = (
        base_url_match.group(1)
        .replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace("\\u003d", "=")
        .replace("\\u003f", "?")
    )
    if "timedtext" not in caption_url and "caption" not in caption_url.lower():
        return None
    return caption_url


def _parse_caption_response(content: bytes) -> list:
    """Timedtext yanıtını (XML veya JSON) parse edip segment listesi döner."""
    segments_raw = []
    body = content.decode("utf-8", errors="ignore").strip()
    if "<transcript>" in body or "<text " in body:
        try:
            root = ET.fromstring(content)
            for elem in root.findall(".//text"):
                start = float(elem.get("start", 0))
                text = (elem.text or "").strip()
                if text:
                    segments_raw.append({"text": text, "start": start})
        except Exception:
            pass
    if not segments_raw and ("[" in body and '"text"' in body):
        try:
            data = json.loads(body)
            events = data.get("events", data) if isinstance(data, dict) else []
            if not isinstance(events, list):
                events = data if isinstance(data, list) else []
            for ev in events:
                segs = ev.get("segs", [])
                text = "".join(s.get("utf8", s.get("text", "")) for s in segs).strip()
                if not text or text == "\\n":
                    continue
                start = ev.get("tStartMs", 0) / 1000.0
                segments_raw.append({"text": text, "start": start})
        except Exception:
            pass
    return segments_raw


def _fetch_caption_track_by_url(client, caption_url: str) -> Tuple[list, Optional[str]]:
    """Caption timedtext URL'sini ScrapingBee ile çeker, segment listesi döner."""
    params = _scrapingbee_base_params()
    try:
        resp = client.get(caption_url, params=params)
    except Exception as e:
        return [], str(e)
    if resp.status_code != 200 or not resp.content:
        return [], None
    segments_raw = _parse_caption_response(resp.content)
    if segments_raw:
        return segments_raw, None
    return [], None


def _fetch_caption_track_from_page(html: bytes, client) -> Tuple[list, Optional[str]]:
    """Sayfa HTML'inde captionTracks baseUrl arar, ScrapingBee ile çeker, segment listesi döner."""
    caption_url = _extract_caption_base_url(html)
    if not caption_url:
        return [], None
    return _fetch_caption_track_by_url(client, caption_url)


def _segments_raw_to_result(segments_raw: list) -> list:
    """Ham segment listesini {text, start, duration} formatına çevirir."""
    result = []
    for i, item in enumerate(segments_raw):
        start = float(item.get("start") or 0)
        next_start = (
            segments_raw[i + 1].get("start") if i + 1 < len(segments_raw) else start + 5
        )
        duration = (
            max(0.1, next_start - start)
            if isinstance(next_start, (int, float))
            else 5.0
        )
        result.append({"text": item["text"], "start": start, "duration": duration})
    return result


def fetch_transcript_scrapingbee(video_id: str) -> Tuple[list, Optional[str]]:
    """
    Önce render_js=False ile watch sayfası alır, HTML'den caption track URL çıkarıp
    timedtext ile transkript döner. Bulunamazsa veya hata olursa render_js=True +
    js_scenario ile paneli açıp DOM'dan parse eder (kredi dostu hibrit yapı).
    Returns: (segments, error_message)
    """
    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None) or None
    if not api_key or not api_key.strip():
        return [], "SCRAPINGBEE_API_KEY ayarlanmamış."

    url = f"https://www.youtube.com/watch?v={video_id}"
    base_params = _scrapingbee_base_params()

    try:
        from scrapingbee import ScrapingBeeClient
    except ImportError:
        return [], "scrapingbee yüklü değil: pip install scrapingbee"

    client = ScrapingBeeClient(api_key=api_key.strip())

    # ——— Aşama 1: Ucuz istek – sadece HTML (render_js=False)
    try:
        response = client.get(
            url,
            params={
                **base_params,
                "render_js": False,
            },
        )
    except Exception as e:
        return [], f"ScrapingBee istek hatası: {e}"

    if response.status_code != 200:
        msg = _scrapingbee_error_message(response.status_code)
        if msg:
            return [], msg
        return [], f"ScrapingBee HTTP {response.status_code}"

    html = response.content
    if not html:
        return [], "ScrapingBee boş yanıt döndü."

    caption_url = _extract_caption_base_url(html)
    if caption_url:
        segments_raw, err = _fetch_caption_track_by_url(client, caption_url)
        if segments_raw:
            return _segments_raw_to_result(segments_raw), None
        # Parse hatası veya 4xx/5xx → Aşama 2'ye geç

    # ——— Aşama 2: JS rendering + transkript panelini aç
    js_scenario = {
        "instructions": [
            {"wait": 4000},
            {"scroll_y": 500},
            {"wait": 2000},
            {"wait_for_and_click": "ytd-video-description-transcript-section-renderer button"},
            {"wait": 1500},
            {"wait_for_and_click": "[data-target-id='engagement-panel-transcript'] button"},
            {"wait": 3000},
            {"wait_for": "#segments-container"},
        ],
        "strict": False,
    }

    try:
        response = client.get(
            url,
            params={
                **base_params,
                "render_js": True,
                "js_scenario": js_scenario,
            },
        )
    except Exception as e:
        return [], f"ScrapingBee istek hatası: {e}"

    if response.status_code != 200:
        msg = _scrapingbee_error_message(response.status_code)
        if msg:
            return [], msg
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
        segments_raw, err = _fetch_caption_track_from_page(html, client)
        if segments_raw:
            return _segments_raw_to_result(segments_raw), None
        return [], err or "Transkript alanı bulunamadı (video altyazı desteklemiyor olabilir)."

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

    return _segments_raw_to_result(segments_raw), None


def _scrapingbee_error_message(status_code: int) -> Optional[str]:
    """HTTP durum koduna göre kullanıcı mesajı döner."""
    if status_code == 401:
        return "ScrapingBee API key geçersiz veya eksik. .env dosyasında SCRAPINGBEE_API_KEY kontrol edin."
    if status_code == 403:
        return "ScrapingBee erişim reddedildi (API key veya kota). Dashboard: https://www.scrapingbee.com"
    if status_code == 429:
        return "ScrapingBee kota aşıldı. Biraz bekleyin veya planı yükseltin."
    if status_code >= 500:
        return f"ScrapingBee sunucu hatası ({status_code}). Kısa süre sonra tekrar deneyin."
    return None
