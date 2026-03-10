#!/usr/bin/env python3
"""
YouTube transkript: youtube-transcript-api (birincil) + yt-dlp fallback.
Cookie, User-Agent ve opsiyonel proxy destekli.
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def _extract_video_id(value: str) -> Optional[str]:
    if not value or not value.strip():
        return None
    value = value.strip()
    if re.match(r"^[a-zA-Z0-9_-]{11}$", value):
        return value
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", value)
    if m:
        return m.group(1)
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", value)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com/embed/([a-zA-Z0-9_-]{11})", value)
    if m:
        return m.group(1)
    return None


def _load_cookies_from_file(path: str) -> Optional["http.cookiejar.MozillaCookieJar"]:
    try:
        from http.cookiejar import MozillaCookieJar
        jar = MozillaCookieJar()
        jar.load(str(path), ignore_discard=True, ignore_expires=True)
        return jar
    except Exception:
        return None


def _create_http_client(
    cookies_path: Optional[str] = None,
    use_random_ua: bool = True,
    proxy: Optional[str] = None,
) -> "requests.Session":
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    headers["User-Agent"] = random.choice(USER_AGENTS) if use_random_ua else USER_AGENTS[0]
    session.headers.update(headers)

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    if cookies_path:
        jar = _load_cookies_from_file(cookies_path)
        if jar:
            session.cookies.update(jar)

    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _parse_subtitle_json3(raw: str) -> List[dict]:
    out = []
    try:
        data = json.loads(raw)
        events = data.get("events") or []
        for i, ev in enumerate(events):
            segs = ev.get("segs") or []
            text = "".join((s.get("utf8", "") or "").strip() for s in segs).strip()
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
    except (json.JSONDecodeError, TypeError):
        pass
    return out


def _parse_subtitle_vtt(raw: str) -> List[dict]:
    out = []
    ts_re = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})"
    )
    ts_re_short = re.compile(r"(\d{1,2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}):(\d{2})\.(\d{3})")

    def ts_to_sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    for block in raw.split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        m = ts_re.match(lines[0])
        if m:
            h1, m1, s1, ms1 = m.group(1), m.group(2), m.group(3), m.group(4)
            h2, m2, s2, ms2 = m.group(5), m.group(6), m.group(7), m.group(8)
        else:
            ms = ts_re_short.match(lines[0])
            if not ms:
                continue
            h1, m1, s1, ms1 = "0", ms.group(1), ms.group(2), ms.group(3)
            h2, m2, s2, ms2 = "0", ms.group(4), ms.group(5), ms.group(6)
        text = " ".join(l.strip() for l in lines[1:] if l.strip()).strip()
        if not text:
            continue
        start = ts_to_sec(h1, m1, s1, ms1)
        end = ts_to_sec(h2, m2, s2, ms2)
        out.append({"text": text, "start": start, "duration": max(0.1, end - start)})
    return out


def _fetch_transcript_ytdlp(video_id: str, languages: tuple, proxy: Optional[str] = None) -> Tuple[List[dict], Optional[str]]:
    try:
        import yt_dlp
    except ImportError:
        return [], "yt-dlp yüklü değil: pip install yt-dlp"

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": list(languages) or ["tr", "en"],
    }
    if proxy:
        ydl_opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return [], f"yt-dlp: {e}"

    if not info:
        return [], "yt-dlp video bilgisi alınamadı."

    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    all_subs = dict(subs)
    for lang, entries in auto.items():
        if lang not in all_subs:
            all_subs[lang] = entries

    sub_entries = None
    for lang in languages:
        if lang in all_subs:
            sub_entries = all_subs[lang]
            break
    if not sub_entries:
        sub_entries = list(all_subs.values())[0] if all_subs else None
    if not sub_entries:
        return [], "yt-dlp: Bu video için altyazı bulunamadı."

    entry = None
    for e in sub_entries:
        if e.get("url"):
            entry = e
            break
    if not entry:
        return [], "yt-dlp: Altyazı URL'si alınamadı."
    sub_url = entry.get("url")

    try:
        import requests
        kw = {"timeout": 30, "headers": {"User-Agent": random.choice(USER_AGENTS)}}
        if proxy:
            kw["proxies"] = {"http": proxy, "https": proxy}
        resp = requests.get(sub_url, **kw)
        resp.raise_for_status()
        raw = resp.text
    except Exception as e:
        return [], f"yt-dlp: Altyazı indirilemedi: {e}"

    if raw.strip().startswith("{"):
        segments = _parse_subtitle_json3(raw)
    else:
        segments = _parse_subtitle_vtt(raw)
    if not segments:
        return [], "yt-dlp: Altyazı parse edilemedi."
    return segments, None


def _fetch_transcript_youtube_api(
    video_id: str,
    cookies_path: Optional[str],
    languages: tuple,
    proxy: Optional[str] = None,
) -> Tuple[List[dict], Optional[str]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            CookieInvalid,
            CookiePathInvalid,
            CouldNotRetrieveTranscript,
            IpBlocked,
            NoTranscriptFound,
            RequestBlocked,
            TranscriptsDisabled,
            VideoUnavailable,
            VideoUnplayable,
        )
    except ImportError as e:
        return [], f"youtube-transcript-api yüklü değil: pip install youtube-transcript-api\nDetay: {e}"

    http_client = _create_http_client(cookies_path=cookies_path, use_random_ua=True, proxy=proxy)

    try:
        api = YouTubeTranscriptApi(http_client=http_client)
        transcript = api.fetch(video_id, languages=list(languages))
        try:
            segments = transcript.to_raw_data()
        except AttributeError:
            segments = [
                {
                    "text": getattr(s, "text", s.get("text", "")),
                    "start": getattr(s, "start", s.get("start", 0)),
                    "duration": getattr(s, "duration", s.get("duration", 0)),
                }
                for s in transcript
            ]
        return segments, None
    except TranscriptsDisabled:
        return [], "Bu videonun transkriptleri kapalı."
    except NoTranscriptFound:
        return [], f"Bu video için uygun dilde transkript bulunamadı. İstenen diller: {', '.join(languages)}"
    except VideoUnavailable:
        return [], "Video mevcut değil veya silinmiş."
    except VideoUnplayable:
        return [], "Video oynatılamıyor."
    except IpBlocked:
        return [], "IP engeli. Proxy veya cookies.txt deneyin."
    except RequestBlocked:
        return [], "İstek engellendi. Proxy veya cookies.txt deneyin."
    except CookieInvalid:
        return [], "cookies.txt geçersiz veya süresi dolmuş."
    except CookiePathInvalid:
        return [], f"cookies.txt bulunamadı: {cookies_path}"
    except CouldNotRetrieveTranscript:
        return [], "Transkript alınamadı."
    except Exception as e:
        return [], f"Beklenmeyen hata: {e}"


def _try_with_proxy(
    video_id: str,
    cookies_path: Optional[str],
    languages: tuple,
    use_ytdlp_fallback: bool,
    proxy: Optional[str],
) -> Tuple[List[dict], Optional[str]]:
    """Tek proxy (veya None) ile youtube_transcript_api + yt-dlp fallback dener."""
    segments, error = _fetch_transcript_youtube_api(
        video_id, cookies_path, languages, proxy=proxy
    )
    if segments:
        return segments, None
    if use_ytdlp_fallback:
        ytdlp_segments, ytdlp_error = _fetch_transcript_ytdlp(
            video_id, languages, proxy=proxy
        )
        if ytdlp_segments:
            return ytdlp_segments, None
        error = error or ytdlp_error
    return [], error


def fetch_transcript(
    video_id: str,
    cookies_path: Optional[str] = None,
    languages: tuple = ("tr", "en"),
    use_ytdlp_fallback: bool = True,
    proxy_list: Optional[List[str]] = None,
) -> tuple:
    """
    Proxy rotation: proxy_list içindeki her proxy ile dener; hepsi başarısızsa
    son çare olarak proxy olmadan (kendi IP) bir kez daha dener.
    """
    proxy_list = proxy_list or []
    last_error = None

    for proxy in proxy_list:
        try:
            segments, error = _try_with_proxy(
                video_id, cookies_path, languages, use_ytdlp_fallback, proxy
            )
            if segments:
                return segments, None
            last_error = error
        except Exception as e:
            print(f"Proxy başarısız oldu: {proxy}. Bir sonraki deneniyor...", file=sys.stderr)
            continue

    # Son çare: proxy olmadan (direct) dene
    try:
        segments, error = _try_with_proxy(
            video_id, cookies_path, languages, use_ytdlp_fallback, None
        )
        if segments:
            return segments, None
        last_error = error
    except Exception as e:
        last_error = str(e)

    return [], last_error


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube video transkriptini çeker")
    parser.add_argument("video", help="Video ID veya YouTube URL")
    parser.add_argument("-c", "--cookies", default="cookies.txt", help="cookies.txt dosya yolu")
    parser.add_argument("--no-cookies", action="store_true", help="Cookies kullanma")
    parser.add_argument("-l", "--languages", default="tr,en", help="Dil kodları (virgülle)")
    parser.add_argument("-o", "--output", help="Çıktıyı dosyaya yaz (JSON)")
    parser.add_argument("--no-fallback", action="store_true", help="yt-dlp fallback kullanma")
    parser.add_argument(
        "--proxy",
        default=None,
        help="Tek proxy veya virgülle ayrılmış liste (örn: http://user:pass@ip:port)",
    )
    args = parser.parse_args()

    video_id = _extract_video_id(args.video)
    if not video_id:
        print("Hata: Geçersiz video ID veya URL.", file=sys.stderr)
        return 1

    cookies_path = None if args.no_cookies else Path(args.cookies)
    if cookies_path and not cookies_path.is_file():
        cookies_path = None
    cookies_str = str(cookies_path) if cookies_path else None

    raw_proxy = (args.proxy or "").strip()
    proxy_list = [p.strip() for p in raw_proxy.split(",") if p.strip()] if raw_proxy else []

    languages = tuple(l.strip() for l in args.languages.split(",") if l.strip()) or ("tr", "en")
    segments, error = fetch_transcript(
        video_id,
        cookies_path=cookies_str,
        languages=languages,
        use_ytdlp_fallback=not args.no_fallback,
        proxy_list=proxy_list,
    )

    if error:
        print(f"Hata: {error}", file=sys.stderr)
        return 1

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        print(f"Transkript kaydedildi: {out_path}")
    else:
        for s in segments:
            t = s.get("text", "").strip()
            if t:
                print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
