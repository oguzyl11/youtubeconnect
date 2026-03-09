"""
Django modelleri.
"""
from django.db import models


class YouTubeTranscript(models.Model):
    """FastAPI transkript mikroservisinden gelen transkript kayıtları."""

    video_url = models.URLField()
    video_id = models.CharField(max_length=50)
    title = models.CharField(max_length=255, null=True, blank=True)
    raw_text = models.TextField(null=True)
    clean_text = models.TextField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "YouTube Transkript"
        verbose_name_plural = "YouTube Transkriptler"
        ordering = ["-created_at"]

    def __str__(self):
        return self.video_id
