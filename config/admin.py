from django.contrib import admin
from config.models import YouTubeTranscript


@admin.register(YouTubeTranscript)
class YouTubeTranscriptAdmin(admin.ModelAdmin):
    list_display = ("video_id", "title", "created_at")
    search_fields = ("video_id", "title")
    readonly_fields = ("created_at",)
