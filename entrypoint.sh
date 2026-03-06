#!/bin/bash
set -e

# Sunucu: ortam production olarak çalışsın
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"

# Veritabanı hazır olana kadar bekle (DATABASE_URL varsa)
if [ -n "$DATABASE_URL" ]; then
  echo "Waiting for database..."
  for i in $(seq 1 30); do
    if python -c "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null; then
      echo "Database is ready."
      break
    fi
    [ $i -eq 30 ] && echo "Database timeout." && exit 1
    sleep 2
  done
fi

# Migrations
python manage.py migrate --noinput

# Static dosyalar (sunucuda Nginx varsa bu volume'dan servis edilir)
python manage.py collectstatic --noinput 2>/dev/null || true

exec "$@"
