#!/usr/bin/env python3
"""
Playwright ile YouTube transkript çekme.
Ağ trafiğinde api/timedtext yanıtını yakalar; bot tespitini azaltmak için stealth kullanır.
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Yakalanan timedtext: body veya URL (body bazen boş geliyor, URL ile sonra fetch ederiz)
_captured_timedtext: List[bytes] = []
_captured_timedtext_urls: List[str] = []


def _handle_response(response: Any) -> None:
    """Ağ yanıtlarını dinler; timedtext URL'sini saklar (body handler'da güvenilir değil)."""
    try:
        url = (response.url or "").lower()
        if "api/timedtext" not in url:
            return
        if response.status != 200:
            return
        _captured_timedtext_urls.append(response.url)
    except Exception:
        pass


def _parse_timedtext_json3(raw: bytes) -> List[dict]:
    """YouTube timedtext JSON3 formatını [{"text", "start", "duration"}, ...] listesine çevirir."""
    out: List[dict] = []
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
        events = data.get("events") or []
        for i, ev in enumerate(events):
            segs = ev.get("segs") or []
            text = "".join((s.get("utf8") or "").strip() for s in segs).strip()
            if not text or text == "\n":
                continue
            start = ev.get("tStartMs", 0) / 1000.0
            dur_ms = ev.get("dDurationMs")
            if dur_ms is not None:
                duration = dur_ms / 1000.0
            elif i + 1 < len(events):
                duration = (events[i + 1].get("tStartMs", start * 1000) - ev.get("tStartMs", 0)) / 1000.0
            else:
                duration = 5.0
            out.append({"text": text, "start": start, "duration": max(0.1, duration)})
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        pass
    return out


def _parse_timedtext_xml(raw: bytes) -> List[dict]:
    """YouTube timedtext XML'ini [{"text", "start", "duration"}, ...] listesine çevirir."""
    import xml.etree.ElementTree as ET
    out: List[dict] = []
    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
        for elem in root.iter():
            if elem.tag.endswith("text") or (elem.tag == "text"):
                start = float(elem.get("start", 0))
                dur = float(elem.get("dur", elem.get("duration", 5)))
                text = (elem.text or "").strip()
                if text:
                    out.append({"text": text, "start": start, "duration": max(0.1, dur)})
    except Exception:
        pass
    return out


def _ensure_youtube_watch_url(video_url: str) -> str:
    """URL'yi watch formatına getirir (video_id varsa)."""
    url = (video_url or "").strip()
    if not url:
        return url
    # youtu.be/ID -> watch?v=ID
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    if "youtube.com" in url and "/watch" not in url:
        m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    if not url.startswith("http"):
        url = "https://" + url
    return url


def fetch_transcript_with_playwright(video_url: str) -> dict:
    """
    Playwright (Chromium + stealth) ile video sayfasını açar, ağda api/timedtext
    yanıtını yakalar, segment listesine çevirir ve utils/cleaner ile temizleyip döner.

    Returns:
        {"segments": [...], "clean_text": "...", "raw_text": "..."}
        veya hata durumunda {"error": "..."}
    """
    global _captured_timedtext, _captured_timedtext_urls
    _captured_timedtext = []
    _captured_timedtext_urls = []

    url = _ensure_youtube_watch_url(video_url)
    if not url:
        return {"error": "Geçersiz video URL."}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "playwright yüklü değil: pip install playwright && playwright install chromium"}

    try:
        from playwright_stealth import stealth_sync
    except ImportError:
        stealth_sync = None

    segments: List[dict] = []
    dom_segments_holder: List[List[dict]] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                locale="en-US",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            if stealth_sync:
                stealth_sync(page)

            page.on("response", _handle_response)
            # timedtext yanıtını ana akışta bekle; body() callback'te hata veriyor
            with page.expect_response(
                lambda r: "api/timedtext" in (r.url or "").lower(),
                timeout=60000,
            ) as resp_holder:
                page.goto(url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(8000)
            try:
                resp = resp_holder.value
                if resp and resp.status == 200:
                    body = resp.body()
                    if body and len(body) > 10:
                        _captured_timedtext.append(body)
            except Exception:
                pass
            for fetch_url in _captured_timedtext_urls:
                if _captured_timedtext:
                    break
                try:
                    req_resp = context.request.get(fetch_url, timeout=10000)
                    if req_resp.status == 200:
                        b = req_resp.body()
                        if b and len(b) > 10:
                            _captured_timedtext.append(b)
                            break
                except Exception:
                    pass
                if _captured_timedtext:
                    break
                try:
                    import requests as req
                    r = req.get(
                        fetch_url,
                        timeout=8,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept-Language": "en-US,en;q=0.9",
                        },
                    )
                    if r.status_code == 200 and r.content and len(r.content) > 10:
                        _captured_timedtext.append(r.content)
                        break
                except Exception:
                    pass
            # Yedek: Transkripti DOM'dan al (transkript panelini aç, metni çek)
            if not _captured_timedtext:
                try:
                    page.wait_for_timeout(2000)
                    page.evaluate("window.scrollBy(0, 400)")
                    page.wait_for_timeout(1500)
                    # Transkript / "Show transcript" butonları
                    for selector in [
                        "ytd-video-description-transcript-section-renderer button",
                        "button[aria-label*='transcript'], button[aria-label*='Transcript']",
                        "#primary-button ytd-button-renderer",
                    ]:
                        try:
                            btn = page.locator(selector).first
                            if btn.is_visible(timeout=2000):
                                btn.click()
                                page.wait_for_timeout(3000)
                                break
                        except Exception:
                            continue
                    texts = page.evaluate("""() => {
                        const sel = document.querySelector('#segments-container') || document.querySelector('ytd-transcript-segment-renderer');
                        const root = sel ? (sel.closest('ytd-engagement-panel-section-list-renderer') || document) : document;
                        const nodes = root.querySelectorAll('yt-formatted-string.segment-text, ytd-transcript-segment-renderer yt-formatted-string, [id="segments-container"] yt-formatted-string');
                        return Array.from(nodes).map(n => (n.textContent || '').trim()).filter(Boolean);
                    }""")
                    if texts and isinstance(texts, list) and len(texts) > 0:
                        dom_segments_holder.append([{"text": t.strip(), "start": 0, "duration": 0} for t in texts if t.strip()])
                except Exception:
                    pass
            # with bloğu çıkılınca tarayıcı otomatik kapanır
    except Exception as e:
        return {"error": f"Playwright hatası: {e}"}

    # Yakalanan timedtext body'lerinden JSON veya XML parse et
    for body in _captured_timedtext:
        if body.strip().startswith(b"{"):
            segments = _parse_timedtext_json3(body)
            if segments:
                break
        elif b"<transcript>" in body or b"<text " in body:
            segments = _parse_timedtext_xml(body)
            if segments:
                break
    _captured_timedtext = []
    _captured_timedtext_urls = []

    if not segments and dom_segments_holder:
        segments = dom_segments_holder[0]
    if not segments:
        return {
            "error": "Bu video için transkript alınamadı (timedtext body boş, DOM fallback de sonuç vermedi). "
            "Önce scripts/fetch_transcript.py (youtube-transcript-api veya yt-dlp) deneyin."
        }

    raw_text = " ".join(s.get("text", "") for s in segments if s.get("text")).strip()

    # utils/cleaner.py formatına uygun temizleme (varsa)
    clean_text = raw_text
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

    return {
        "segments": segments,
        "raw_text": raw_text,
        "clean_text": clean_text,
    }
