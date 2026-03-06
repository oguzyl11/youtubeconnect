"""
Template context processors.
"""
from django.conf import settings


def base_url(request):
    """Şablonlarda BASE_URL kullanımı için."""
    return {"BASE_URL": settings.BASE_URL}
