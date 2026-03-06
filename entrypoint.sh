#!/bin/bash
set -e

# Veritabanı hazır olana kadar bekle (PostgreSQL)
if [ -n "$DATABASE_URL" ]; then
  echo "Waiting for database..."
  while ! python -c "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null; do
    sleep 2
  done
  echo "Database is ready."
fi

# Migrations
python manage.py migrate --noinput

# Static dosyalar (production)
python manage.py collectstatic --noinput --clear 2>/dev/null || true

exec "$@"
