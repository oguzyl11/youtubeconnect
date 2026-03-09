#!/usr/bin/env python3
"""
YouTube videolarından transkript çekmek için bağımsız script.
- youtube-transcript-api kullanır (birincil)
- Fallback: youtube-transcript-api başarısız olursa yt-dlp ile dener
- cookies.txt (Netscape format) ile bot engelini aşmayı dener
- Her istekte farklı User-Agent gönderir
- Detaylı hata yönetimi
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Proje kökünü path'e ekle
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# User-Agent havuzu – her istekte rastgele seçilir
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]


def _extract_video_id(value: str) -> Optional[str]:
    """URL veya ham video ID'den ID çıkarır."""
    if not value or not value.strip():
        return None
    value = value.strip()
    # Zaten 11 karakterlik ID mi?
    if re.match(r"^[a-zA-Z0-9_-]{11}$", value):
        return value
    # youtu.be/ID
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", value)
    if m:
        return m.group(1)
    # youtube.com/watch?v=ID
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", value)
    if m:
        return m.group(1)
    # youtube.com/embed/ID
    m = re.search(r"youtube\.com/embed/([a-zA-Z0-9_-]{11})", value)
    if m:
        return m.group(1)
    return None


def _load_cookies_from_file(path: str) -> Optional["http.cookiejar.MozillaCookieJar"]:
    """Netscape formatındaki cookies.txt dosyasını yükler."""
    try:
        from http.cookiejar import MozillaCookieJar

        jar = MozillaCookieJar()
        jar.load(str(path), ignore_discard=True, ignore_expires=True)
        return jar
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _create_http_client(
    cookies_path: Optional[str] = None,
    use_random_ua: bool = True,
) -> "requests.Session":
    """Cookies ve rastgele User-Agent ile Session oluşturur."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()

    headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if use_random_ua:
        headers["User-Agent"] = random.choice(USER_AGENTS)
    else:
        headers["User-Agent"] = USER_AGENTS[0]
    session.headers.update(headers)

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
    """YouTube json3 formatını [{"text", "start", "duration"}, ...] listesine çevirir."""
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
    """WebVTT formatını [{"text", "start", "duration"}, ...] listesine çevirir."""
    out = []

    def ts_to_sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    # HH:MM:SS.mmm --> HH:MM:SS.mmm veya MM:SS.mmm --> MM:SS.mmm
    ts_re = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})"
    )
    # MM:SS.mmm --> MM:SS.mmm (saat yok)
    ts_re_short = re.compile(
        r"(\d{1,2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}):(\d{2})\.(\d{3})"
    )

    for block in raw.split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        m = ts_re.match(lines[0]) or None
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
        duration = max(0.1, end - start)
        out.append({"text": text, "start": start, "duration": duration})
    return out


def _fetch_transcript_ytdlp(video_id: str, languages: tuple) -> Tuple[List[dict], Optional[str]]:
    """
    yt-dlp ile transkript çeker (fallback).
    writesubtitles + writeautomaticsub, sadece altyazı URL'si alınır, videoyu indirmez.
    Altyazı içeriği HTTP ile çekilip bellekte parse edilir.
    Returns: (segments, error_message)
    """
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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return [], f"yt-dlp: {e}"

    if not info:
        return [], "yt-dlp video bilgisi alınamadı."

    # subtitles (manuel) + automatic_captions (otomatik) birleştir
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    all_subs = dict(subs)
    for lang, entries in auto.items():
        if lang not in all_subs:
            all_subs[lang] = entries

    # Öncelik sırasına göre dil seç
    sub_entries = None
    for lang in languages:
        if lang in all_subs:
            sub_entries = all_subs[lang]
            break
    if not sub_entries:
        sub_entries = list(all_subs.values())[0] if all_subs else None

    if not sub_entries:
        return [], "yt-dlp: Bu video için altyazı bulunamadı."

    # json3 > vtt > srv3 tercih et
    entry = None
    for ext in ("json3", "vtt", "srv3"):
        for e in sub_entries:
            if e.get("ext") == ext and e.get("url"):
                entry = e
                break
        if entry:
            break
    if not entry:
        entry = sub_entries[0]
    sub_url = entry.get("url")
    if not sub_url:
        return [], "yt-dlp: Altyazı URL'si alınamadı."

    # Altyazı içeriğini HTTP ile belleğe çek
    try:
        import requests
        resp = requests.get(sub_url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=30)
        resp.raise_for_status()
        raw = resp.text
    except Exception as e:
        return [], f"yt-dlp: Altyazı indirilemedi: {e}"

    # Parse
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
) -> Tuple[List[dict], Optional[str]]:
    """youtube-transcript-api ile transkript çeker. Returns: (segments, error_message)"""
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

    http_client = _create_http_client(cookies_path=cookies_path, use_random_ua=True)

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
        return [], (
            "Bu videonun transkriptleri kapalı. "
            "Video sahibi altyazı/transkript özelliğini devre dışı bırakmış."
        )
    except NoTranscriptFound:
        return [], (
            "Bu video için uygun dilde transkript bulunamadı. "
            f"İstenen diller: {', '.join(languages)}"
        )
    except VideoUnavailable:
        return [], "Video mevcut değil veya silinmiş."
    except VideoUnplayable:
        return [], "Video oynatılamıyor (yaş kısıtlaması veya bölgesel kısıtlama olabilir)."
    except IpBlocked:
        return [], (
            "IP adresiniz YouTube tarafından geçici olarak engellenmiş (bot koruması). "
            "Çözüm: cookies.txt kullanın, VPN/proxy deneyin veya bir süre bekleyin."
        )
    except RequestBlocked:
        return [], (
            "İstek bot koruması nedeniyle engellendi. "
            "Çözüm: Geçerli bir cookies.txt (Netscape format) kullanın veya VPN/proxy deneyin."
        )
    except CookieInvalid:
        return [], (
            "cookies.txt geçersiz veya süresi dolmuş. "
            "Tarayıcıdan yeni cookies export edin (Cookie-Editor eklentisi, Netscape format)."
        )
    except CookiePathInvalid:
        return [], (
            "cookies.txt dosyası bulunamadı veya okunamıyor. "
            f"Kontrol edin: {cookies_path}"
        )
    except CouldNotRetrieveTranscript:
        return [], (
            "Transkript alınamadı. Video transkript desteklemiyor olabilir "
            "veya YouTube geçici bir hata veriyor. Daha sonra tekrar deneyin."
        )
    except Exception as e:
        err_msg = str(e).lower()
        if "ip" in err_msg or "blocked" in err_msg or "429" in err_msg:
            return [], (
                "Bot engeli veya IP kısıtlaması tespit edildi. "
                "cookies.txt kullanın veya VPN/proxy deneyin."
            )
        return [], f"Beklenmeyen hata: {e}"


def fetch_transcript(
    video_id: str,
    cookies_path: Optional[str] = None,
    languages: tuple = ("tr", "en"),
    use_ytdlp_fallback: bool = True,
) -> tuple:
    """
    Video ID için transkript döner.
    Önce youtube-transcript-api dener; başarısız olursa yt-dlp fallback kullanır.
    Returns: (segments, error_message)
    """
    segments, error = _fetch_transcript_youtube_api(video_id, cookies_path, languages)
    if segments:
        return segments, None

    if use_ytdlp_fallback:
        ytdlp_segments, ytdlp_error = _fetch_transcript_ytdlp(video_id, languages)
        if ytdlp_segments:
            return ytdlp_segments, None
        error = error or ytdlp_error

    return [], error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="YouTube video transkriptini çeker (youtube-transcript-api)"
    )
    parser.add_argument(
        "video",
        help="Video ID veya YouTube URL (örn: dQw4w9WgXcQ veya https://youtube.com/watch?v=dQw4w9WgXcQ)",
    )
    parser.add_argument(
        "-c",
        "--cookies",
        default="cookies.txt",
        help="Netscape formatında cookies.txt dosya yolu (varsayılan: cookies.txt)",
    )
    parser.add_argument(
        "--no-cookies",
        action="store_true",
        help="Cookies kullanma",
    )
    parser.add_argument(
        "-l",
        "--languages",
        default="tr,en",
        help="Öncelik sırasına göre dil kodları (virgülle ayrılmış, varsayılan: tr,en)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Çıktıyı dosyaya yaz (JSON)",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="yt-dlp fallback kullanma (sadece youtube-transcript-api)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Metni temizle (zaman damgası, HTML, tekrarlar, [Music] vb.)",
    )
    parser.add_argument(
        "--no-sound-effects",
        action="store_true",
        help="Ses efektlerini sakla, [Music]/[Applause] kaldırma (--clean ile)",
    )
    parser.add_argument(
        "--paragraphs",
        action="store_true",
        help="Temiz metni paragraflara böl (--clean ile, her 5 cümle/500 karakter)",
    )
    args = parser.parse_args()

    video_id = _extract_video_id(args.video)
    if not video_id:
        print("Hata: Geçersiz video ID veya URL.", file=sys.stderr)
        return 1

    cookies_path = None if args.no_cookies else Path(args.cookies)
    if cookies_path and not cookies_path.is_file():
        print(f"Uyarı: cookies.txt bulunamadı ({cookies_path}), cookies olmadan deneniyor.", file=sys.stderr)
        cookies_path = None
    cookies_str = str(cookies_path) if cookies_path else None

    languages = tuple(l.strip() for l in args.languages.split(",") if l.strip()) or ("tr", "en")
    segments, error = fetch_transcript(
        video_id,
        cookies_path=cookies_str,
        languages=languages,
        use_ytdlp_fallback=not args.no_fallback,
    )

    if error:
        print(f"Hata: {error}", file=sys.stderr)
        return 1

    if args.clean:
        try:
            from utils.cleaner import clean_transcript
        except ImportError:
            sys.path.insert(0, str(ROOT))
            from utils.cleaner import clean_transcript

        cleaned = clean_transcript(
            segments,
            remove_sound_effects_flag=not args.no_sound_effects,
            deduplicate_words=True,
            split_paragraphs=args.paragraphs,
        )
        if args.output:
            out_path = Path(args.output)
            with open(out_path, "w", encoding="utf-8") as f:
                if isinstance(cleaned, list):
                    f.write("\n\n".join(cleaned))
                else:
                    f.write(cleaned)
            print(f"Temiz transkript kaydedildi: {out_path}")
        else:
            if isinstance(cleaned, list):
                for para in cleaned:
                    print(para)
                    print()
            else:
                print(cleaned)
        return 0

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        print(f"Transkript {len(segments)} segment olarak kaydedildi: {out_path}")
    else:
        for s in segments:
            t = s.get("text", "").strip()
            if t:
                print(t)

    return 0


if __name__ == "__main__":
    sys.exit(main())
