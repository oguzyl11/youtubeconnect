"""
URL configuration.
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path

from config.views import api_transcript, process_youtube_video, transcript_page

def health(request):
    return HttpResponse("ok", content_type="text/plain")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("", transcript_page),
    path("api/transcript/", api_transcript),
    path("api/process-youtube/", process_youtube_video),
]
