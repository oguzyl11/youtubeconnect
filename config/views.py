"""
Ana sayfa ve transkript API view'ları.
"""
import json
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from config.youtube_utils import extract_youtube_video_id, get_transcript_for_video
from config.services import (
    TranscriptServiceError,
    fetch_transcript_from_microservice,
)
from config.models import YouTubeTranscript


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
    body = {}
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

    # Tarayıcı eklentisi (Chrome extension) ile gönderilen transkript
    transcript_from_browser = (body.get("transcript") or "").strip()
    if transcript_from_browser and request.method == "POST":
        prefix = getattr(settings, "TRANSCRIPT_CACHE_KEY_PREFIX", "yt_transcript:")
        timeout = getattr(settings, "TRANSCRIPT_CACHE_TIMEOUT", 3600)
        cache_key = f"{prefix}{video_id}"
        # Parça parça (her satır veya segment) veya tek blok
        lines = [t.strip() for t in transcript_from_browser.split("\n") if t.strip()]
        if not lines:
            segments = [{"text": transcript_from_browser}]
        else:
            segments = [{"text": line} for line in lines]
        cache.set(cache_key, segments, timeout=timeout)
        return JsonResponse({
            "video_id": video_id,
            "segments": segments,
            "full_text": " ".join(s["text"] for s in segments),
            "source": "browser_extension",
        })

    segments, error = get_transcript_for_video(video_id)
    if error:
        return JsonResponse(
            {"error": (error or "Transkript alınamadı.").strip(), "video_id": video_id},
            status=422,
        )

    return JsonResponse({
        "video_id": video_id,
        "segments": segments,
        "full_text": " ".join(s["text"] for s in segments),
    })


@require_POST
def process_youtube_video(request):
    """
    POST ile youtube_url alır; FastAPI mikroservisinden transkript çeker,
    veritabanında YouTubeTranscript oluşturur veya günceller.
    JSON: {"youtube_url": "https://..."} veya form: youtube_url=...
    """
    youtube_url = None
    content_type = request.content_type or ""
    if "application/json" in content_type and request.body:
        try:
            body = json.loads(request.body)
            youtube_url = (body.get("youtube_url") or body.get("url") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pass
    if not youtube_url:
        youtube_url = (request.POST.get("youtube_url") or request.POST.get("url") or "").strip()

    if not youtube_url:
        return JsonResponse(
            {"error": "youtube_url veya url parametresi gerekli."},
            status=400,
        )

    try:
        data = fetch_transcript_from_microservice(youtube_url)
    except TranscriptServiceError as e:
        return JsonResponse(
            {"error": str(e)},
            status=422,
        )
    except Exception as e:
        return JsonResponse(
            {"error": f"Beklenmeyen hata: {e}"},
            status=500,
        )

    video_id = data.get("video_id") or ""
    title = data.get("title")
    raw_text = data.get("raw_text")
    clean_text = data.get("clean_text")

    try:
        obj, created = YouTubeTranscript.objects.update_or_create(
            video_id=video_id,
            defaults={
                "video_url": youtube_url,
                "title": title,
                "raw_text": raw_text,
                "clean_text": clean_text,
            },
        )
    except Exception as e:
        return JsonResponse(
            {"error": f"Veritabanı kaydı oluşturulamadı: {e}"},
            status=500,
        )

    return JsonResponse({
        "status": "ok",
        "message": "Kaydedildi." if created else "Güncellendi.",
        "video_id": obj.video_id,
        "clean_text": obj.clean_text or clean_text or "",
    })
