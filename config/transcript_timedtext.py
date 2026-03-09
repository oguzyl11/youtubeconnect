"""
YouTube transkript: sayfa HTML'inden ytInitialPlayerResponse çıkarıp
timedtext API (baseUrl) ile altyazı indirme. API anahtarı gerekmez.
(youtube-transcript-api / anthiago.com tarzı yöntem)
"""
import json
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Tarayıcı gibi görünmek için
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"
TIMEOUT = 25


def _http_get(url: str, extra_headers: Optional[dict] = None) -> tuple[str, Optional[str]]:
    """URL'ye GET atar; (body, error) döner."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except HTTPError as e:
        return "", f"HTTP {e.code}"
    except URLError as e:
        return "", str(e.reason) if getattr(e, "reason", None) else str(e)
    except Exception as e:
        return "", str(e)


def _extract_json_from_assign(html: str, var_name: str) -> Optional[dict]:
    """HTML içinde 'var_name = { ... };' şeklinde gömülü JSON'u çıkarır (süslü parantez eşlemesi)."""
    pattern = var_name + r"\s*=\s*"
    idx = html.find(pattern)
    if idx == -1:
        return None
    idx = html.find("{", idx)
    if idx == -1:
        return None
    start = idx
    depth = 0
    in_string = False
    escape = False
    quote_char = None
    i = idx
    while i < len(html):
        c = html[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            escape = True
            i += 1
            continue
        if not in_string:
            if c == '"' or c == "'":
                in_string = True
                quote_char = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start : i + 1])
                    except json.JSONDecodeError:
                        return None
            i += 1
            continue
        if c == quote_char:
            in_string = False
        i += 1
    return None


def _get_caption_tracks(player_response: dict) -> list[dict]:
    """player response içinden captionTracks listesini döner."""
    try:
        captions = player_response.get("captions") or {}
        renderer = captions.get("playerCaptionsTracklistRenderer") or {}
        tracks = renderer.get("captionTracks") or []
        return tracks
    except Exception:
        return []


def _extract_base_url_from_html(html: str) -> Optional[str]:
    """HTML içinde timedtext baseUrl'ini regex ile arar (ytInitialPlayerResponse parse edilemezse)."""
    m = re.search(
        r'"baseUrl"\s*:\s*"(https://www\.youtube\.com/api/timedtext[^"]+)"',
        html,
    )
    return m.group(1).replace("\\u0026", "&").replace("\\/", "/") if m else None


def _fetch_caption_content(url: str, prefer_json: bool = True) -> tuple[str, str, Optional[str]]:
    """Caption URL'sini çeker. (body, content_type, error). content_type 'json' veya 'xml'."""
    if prefer_json:
        if "&fmt=" not in url and "?fmt=" not in url:
            url = url + ("&" if "?" in url else "?") + "fmt=json3"
    body, err = _http_get(url)
    if err:
        return "", "", err
    if body.strip().startswith("{"):
        return body, "json", None
    if body.strip().startswith("<"):
        return body, "xml", None
    return body, "text", None


def _parse_caption_json3(raw: str) -> list[dict]:
    """YouTube json3 formatını [{"text": "..."}, ...] listesine çevirir."""
    out = []
    try:
        data = json.loads(raw)
        events = data.get("events") or []
        for ev in events:
            segs = ev.get("segs") or []
            for s in segs:
                text = (s.get("utf8") or "").strip()
                if not text or text == "\n":
                    continue
                out.append({"text": text})
    except json.JSONDecodeError:
        pass
    return out


def _parse_caption_xml(raw: str) -> list[dict]:
    """YouTube timedtext XML'ini [{"text": "..."}, ...] listesine çevirir."""
    out = []
    try:
        root = ET.fromstring(raw)
        for elem in root.iter():
            if elem.tag == "text" and elem.text:
                text = (elem.text or "").strip()
                if text:
                    out.append({"text": text})
            if elem.tag.endswith("text") and elem.text:
                text = (elem.text or "").strip()
                if text:
                    out.append({"text": text})
    except ET.ParseError:
        pass
    return out


def fetch_transcript_timedtext(video_id: str) -> tuple[list, Optional[str]]:
    """
    1) YouTube watch sayfasını çeker.
    2) ytInitialPlayerResponse içinden captionTracks.baseUrl alır.
    3) baseUrl ile timedtext içeriğini çeker (fmt=json3 tercih).
    4) Parse edip [{"text": "..."}, ...] döner.
    Returns: (segments, error_message)
    """
    if not video_id or not re.match(r"^[a-zA-Z0-9_-]{11}$", video_id):
        return [], "Geçersiz video ID."

    url = WATCH_URL_TEMPLATE.format(video_id=video_id)
    html, err = _http_get(url)
    if err:
        return [], f"Video sayfası alınamadı: {err}"
    if "ytInitialPlayerResponse" not in html:
        return [], "Sayfada altyazı bilgisi bulunamadı (video kısıtlı veya altyazı yok)."

    player = _extract_json_from_assign(html, "ytInitialPlayerResponse")
    tracks = _get_caption_tracks(player) if player else []

    if not tracks:
        base_url = _extract_base_url_from_html(html)
        if base_url:
            tracks = [{"baseUrl": base_url, "kind": None}]
    if not tracks:
        return [], "Bu video için altyazı bulunamadı."

    # Önce manuel altyazı, sonra ASR (otomatik) tercih et
    chosen = None
    for t in tracks:
        if t.get("kind") != "asr":
            chosen = t
            break
    if not chosen:
        chosen = tracks[0]

    base_url = (chosen.get("baseUrl") or "").strip()
    if not base_url:
        return [], "Altyazı URL'si bulunamadı."

    body, content_type, err = _fetch_caption_content(base_url, prefer_json=True)
    if err:
        return [], f"Altyazı indirilemedi: {err}"

    if content_type == "json":
        segments = _parse_caption_json3(body)
    elif content_type == "xml":
        segments = _parse_caption_xml(body)
    else:
        segments = [{"text": line} for line in body.splitlines() if line.strip()]

    if not segments:
        return [], "Altyazı metni boş veya parse edilemedi."
    return segments, None
