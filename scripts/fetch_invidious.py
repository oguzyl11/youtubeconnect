#!/usr/bin/env python3
"""
Invidious örnekleri üzerinden YouTube altyazı çekme.
Aktif Invidious sunucularını sırayla dener; en/tr altyazıyı seçer, utils/cleaner ile temizler.
"""
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Aktif Invidious örnekleri (fallback listesi)
INVIDIOUS_INSTANCES = [
    "https://vid.puffyan.us",
    "https://invidious.flokinet.to",
    "https://invidious.perennialte.ch",
    "https://invidious.fdn.fr",
    "https://inv.riverside.rocks",
    "https://invidious.slipfox.xyz",
]

TIMEOUT = 10
PREFERRED_LANGS = ("tr", "en")


def _parse_webvtt_to_plain(vtt_text: str) -> str:
    """WebVTT metnini satır satır metne çevirir (zaman satırlarını atlar)."""
    lines = []
    for line in vtt_text.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        lines.append(line)
    return " ".join(lines).strip()


def _clean_text(text: str) -> str:
    """utils/cleaner varsa temizler, yoksa basit boşluk normu uygular."""
    if not text or not text.strip():
        return ""
    try:
        from utils.cleaner import clean_text
        return clean_text(
            text,
            remove_timestamps_flag=True,
            remove_html=True,
            remove_sound_effects_flag=True,
            deduplicate_words=True,
        )
    except ImportError:
        return re.sub(r"\s+", " ", text).strip()


def fetch_transcript_invidious(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Invidious örneklerini sırayla dener; en veya tr altyazıyı alıp temiz metin döner.
    Returns: (clean_text, error_message)
    """
    video_id = (video_id or "").strip()
    if not video_id or len(video_id) != 11:
        return None, "Geçersiz video_id."

    try:
        import requests
    except ImportError:
        return None, "requests yüklü değil: pip install requests"

    for base_url in INVIDIOUS_INSTANCES:
        base_url = base_url.rstrip("/")
        # Önce ?lang= ile doğrudan WebVTT almayı dene (tek istek)
        for lang in PREFERRED_LANGS:
            try:
                url = f"{base_url}/api/v1/captions/{video_id}?lang={lang}"
                r = requests.get(url, timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                body = (r.text or "").strip()
                if not body or len(body) < 20:
                    continue
                if "WEBVTT" in body or "--> " in body:
                    raw = _parse_webvtt_to_plain(body)
                elif body.startswith("{"):
                    try:
                        import json
                        d = json.loads(body)
                        events = d.get("events") or []
                        parts = []
                        for ev in events:
                            for s in ev.get("segs") or []:
                                t = (s.get("utf8") or s.get("text") or "").strip()
                                if t and t != "\n":
                                    parts.append(t)
                        raw = " ".join(parts)
                    except Exception:
                        raw = body
                else:
                    raw = body
                if raw:
                    clean = _clean_text(raw)
                    return (clean or raw), None
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException:
                continue
            except Exception:
                continue
        # Liste endpoint'i ile altyazı URL'lerini al, sonra içeriği çek
        try:
            url = f"{base_url}/api/v1/captions/{video_id}"
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            data = r.json()
            captions = data.get("captions") or []
            if not captions:
                continue
            chosen_url = None
            for cap in captions:
                code = (cap.get("languageCode") or cap.get("language_code") or "").lower()
                if code in PREFERRED_LANGS:
                    chosen_url = cap.get("url")
                    if chosen_url:
                        break
            if not chosen_url:
                chosen_url = (captions[0] or {}).get("url")
            if not chosen_url:
                continue
            if chosen_url.startswith("/"):
                chosen_url = base_url + chosen_url
            r2 = requests.get(chosen_url, timeout=TIMEOUT)
            if r2.status_code != 200:
                continue
            body = (r2.text or "").strip()
            if not body:
                continue
            if "WEBVTT" in body or "--> " in body:
                raw = _parse_webvtt_to_plain(body)
            elif body.startswith("{"):
                try:
                    import json
                    d = json.loads(body)
                    events = d.get("events") or []
                    parts = []
                    for ev in events:
                        for s in ev.get("segs") or []:
                            t = (s.get("utf8") or s.get("text") or "").strip()
                            if t and t != "\n":
                                parts.append(t)
                    raw = " ".join(parts)
                except Exception:
                    raw = body
            else:
                raw = body
            if raw:
                clean = _clean_text(raw)
                return (clean or raw), None
        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.RequestException:
            continue
        except Exception:
            continue

    return None, "Tüm Invidious örnekleri denendi; altyazı alınamadı."


def main() -> int:
    if len(sys.argv) < 2:
        print("Kullanım: python scripts/fetch_invidious.py <video_id>", file=sys.stderr)
        print("Örnek: python scripts/fetch_invidious.py dQw4w9WgXcQ", file=sys.stderr)
        return 1
    video_id = sys.argv[1]
    text, err = fetch_transcript_invidious(video_id)
    if err:
        print(f"Hata: {err}", file=sys.stderr)
        return 1
    print(text or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
