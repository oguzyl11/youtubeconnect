"""
YouTube transkript: sayfa HTML'inden ytInitialPlayerResponse çıkarıp
timedtext API (baseUrl) ile altyazı indirme. API anahtarı gerekmez.
Fallback: Innertube player API (POST youtubei/v1/player).
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
INNERTUBE_PLAYER_BASE = "https://www.youtube.com/youtubei/v1/player"
# Yedek key (sayfada bulunamazsa)
INNERTUBE_KEY_FALLBACK = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9Y21XuKTY"
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


def _http_post_json(url: str, data: dict) -> tuple[Optional[dict], Optional[str]]:
    """POST with JSON body; returns (parsed_json, error)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        body = json.dumps(data).encode("utf-8")
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=TIMEOUT) as resp:
            out = json.loads(resp.read().decode("utf-8", errors="replace"))
            return out, None
    except HTTPError as e:
        return None, f"HTTP {e.code}"
    except URLError as e:
        return None, str(e.reason) if getattr(e, "reason", None) else str(e)
    except json.JSONDecodeError as e:
        return None, f"JSON: {e}"
    except Exception as e:
        return None, str(e)


def _extract_innertube_key(html: str) -> str:
    """HTML'den INNERTUBE_API_KEY çıkarır."""
    m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    return m.group(1) if m else INNERTUBE_KEY_FALLBACK


def _fetch_caption_tracks_innertube(video_id: str, html: str = "") -> tuple[list[dict], Optional[str]]:
    """Innertube player API ile captionTracks döner. (tracks, error)"""
    key = _extract_innertube_key(html) if html else INNERTUBE_KEY_FALLBACK
    url = f"{INNERTUBE_PLAYER_BASE}?key={key}"
    payload = {
        "context": {
            "client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00"},
        },
        "videoId": video_id,
    }
    data, err = _http_post_json(url, payload)
    if err:
        return [], err
    if not data:
        return [], "Innertube yanıt boş"
    try:
        captions = (data.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {}
        tracks = captions.get("captionTracks") or []
        return tracks, None
    except Exception:
        return [], "captionTracks parse edilemedi"


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
        innertube_tracks, _ = _fetch_caption_tracks_innertube(video_id, html)
        if innertube_tracks:
            tracks = innertube_tracks
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
