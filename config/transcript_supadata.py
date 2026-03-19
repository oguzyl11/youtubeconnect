"""
YouTube transkript: Supadata API (yalnızca bu yöntem).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

import requests
from django.conf import settings
from supadata import Supadata, SupadataError
from supadata.types import BatchJob, Transcript, TranscriptChunk

logger = logging.getLogger(__name__)

WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"


def _segments_from_transcript(transcript: Transcript) -> list[dict]:
    content: Any = transcript.content
    if isinstance(content, str):
        text = content.strip()
        return [{"text": text}] if text else []
    if not content:
        return []
    out: list[dict] = []
    for chunk in content:
        if isinstance(chunk, TranscriptChunk):
            t = (chunk.text or "").strip()
            if t:
                seg: dict = {"text": t}
                if chunk.offset is not None:
                    seg["offset_ms"] = chunk.offset
                if chunk.duration is not None:
                    seg["duration_ms"] = chunk.duration
                out.append(seg)
        elif isinstance(chunk, dict):
            t = (chunk.get("text") or "").strip()
            if t:
                seg = {"text": t}
                off = chunk.get("offset")
                dur = chunk.get("duration")
                if off is not None:
                    seg["offset_ms"] = off
                if dur is not None:
                    seg["duration_ms"] = dur
                out.append(seg)
    return out


def _poll_transcript_job(
    api_key: str,
    job_id: str,
    base_url: str,
    max_seconds: int,
) -> tuple[Optional[Transcript], Optional[str]]:
    url_base = base_url.rstrip("/")
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    deadline = time.time() + max_seconds
    poll_url = f"{url_base}/transcript/{job_id}"

    while time.time() < deadline:
        try:
            r = requests.get(poll_url, headers=headers, timeout=120)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            return None, f"Supadata iş durumu alınamadı: {e}"

        status = (data.get("status") or "").lower()
        if status == "completed":
            try:
                transcript = Transcript(
                    content=data.get("content"),
                    lang=data.get("lang") or "",
                    available_langs=data.get("availableLangs")
                    or data.get("available_langs")
                    or [],
                )
                return transcript, None
            except (TypeError, ValueError) as e:
                return None, f"Supadata yanıtı işlenemedi: {e}"
        if status == "failed":
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("details") or str(err)
            else:
                msg = err or data.get("message") or "Transkript işi başarısız."
            return None, str(msg)

        time.sleep(1)

    return None, "Supadata transkript işi zaman aşımına uğradı (video çok uzun olabilir)."


def fetch_transcript_supadata(video_id: str) -> tuple[list, Optional[str]]:
    """
    video_id için Supadata ile transkript döner.
    Returns: (segments, error_message)
    """
    if not video_id or not re.match(r"^[a-zA-Z0-9_-]{11}$", video_id):
        return [], "Geçersiz video ID."

    api_key = getattr(settings, "SUPADATA_API_KEY", None) or ""
    api_key = api_key.strip() if isinstance(api_key, str) else ""
    if not api_key:
        return [], "SUPADATA_API_KEY ayarlı değil (.env içinde tanımlayın)."

    base_url = getattr(
        settings,
        "SUPADATA_BASE_URL",
        "https://api.supadata.ai/v1",
    )
    mode = getattr(settings, "SUPADATA_TRANSCRIPT_MODE", "auto") or "auto"
    max_poll = int(getattr(settings, "SUPADATA_JOB_POLL_MAX_SEC", 280) or 280)

    watch_url = WATCH_URL_TEMPLATE.format(video_id=video_id)
    client = Supadata(api_key=api_key, base_url=base_url)

    try:
        result = client.transcript(url=watch_url, mode=mode, text=False)
    except SupadataError as e:
        logger.warning("supadata transcript error video_id=%s %s", video_id, e)
        return [], str(e)
    except Exception as e:
        logger.exception("supadata transcript exception video_id=%s", video_id)
        return [], str(e)

    if isinstance(result, BatchJob):
        transcript, err = _poll_transcript_job(
            api_key, result.job_id, base_url, max_poll
        )
        if err:
            return [], err
        result = transcript

    if not isinstance(result, Transcript):
        return [], "Supadata beklenmeyen yanıt döndü."

    segments = _segments_from_transcript(result)
    if not segments:
        return [], "Transkript metni boş."
    return segments, None
