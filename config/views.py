"""
Ana sayfa ve transkript API view'ları.
"""
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie

from config.youtube_utils import extract_youtube_video_id, get_transcript_for_video


def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def _check_transcript_rate_limit(request) -> bool:
    """IP başına dakikada TRANSCRIPT_RATE_LIMIT_PER_MINUTE'dan fazla istek engellenir."""
    ip = _get_client_ip(request)
    key = f"transcript_ratelimit:{ip}"
    limit = getattr(settings, "TRANSCRIPT_RATE_LIMIT_PER_MINUTE", 10)
    now = time.time()
    window = 60
    timestamps = cache.get(key) or []
    timestamps = [t for t in timestamps if now - t < window]
    if len(timestamps) >= limit:
        return False
    timestamps.append(now)
    cache.set(key, timestamps, timeout=window + 5)
    return True


@require_GET
@ensure_csrf_cookie
def transcript_page(request):
    """YouTube URL giriş sayfası."""
    return render(request, "transcript.html")


@require_http_methods(["GET", "POST"])
def api_transcript(request):
    """
    Transkript API: GET/POST ile url veya video_id gönderilir.
    GET: ?url=... veya ?video_id=...
    POST (JSON): {"url": "..."} veya {"video_id": "..."}
    """
    if not _check_transcript_rate_limit(request):
        return JsonResponse(
            {"error": "Çok fazla istek. Lütfen bir dakika bekleyin."},
            status=429,
        )

    video_id = None
    if request.method == "GET":
        video_id = request.GET.get("video_id")
        if not video_id and request.GET.get("url"):
            video_id = extract_youtube_video_id(request.GET.get("url"))
    else:
        try:
            import json
            body = json.loads(request.body) if request.body else {}
            video_id = body.get("video_id") or (
                extract_youtube_video_id(body.get("url", ""))
                if body.get("url") else None
            )
        except Exception:
            pass

    if not video_id:
        return JsonResponse(
            {"error": "Geçerli bir YouTube URL veya video_id gerekli."},
            status=400,
        )

    segments, error = get_transcript_for_video(video_id)
    if error:
        err_msg = (error or "Transkript alınamadı.").strip()
        if "SCRAPINGBEE_API_KEY" not in err_msg and ("block" in err_msg.lower() or "ip" in err_msg.lower()):
            err_msg = err_msg.rstrip(".") + ". .env dosyasında SCRAPINGBEE_API_KEY doğru ayarlandığından emin olun (https://www.scrapingbee.com)."
        return JsonResponse(
            {"error": err_msg, "video_id": video_id},
            status=422,
        )

    return JsonResponse({
        "video_id": video_id,
        "segments": segments,
        "full_text": " ".join(s["text"] for s in segments),
    })
