# YouTube Connect – Django (Docker, production)

Docker ile canlıya uygun Django projesi.

## Bağımlılıklar

- **requirements.txt**: Django 4.2, gunicorn, psycopg2-binary, whitenoise, django-cors-headers, django-environ, Pillow, django-health-check
- **requirements-dev.txt**: Geliştirme için ek paketler (debug-toolbar, black, flake8)

## Yerel çalıştırma (Docker olmadan)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # SECRET_KEY ve diğer değişkenleri düzenleyin
python manage.py migrate
python manage.py runserver
```

## Docker ile çalıştırma (production benzeri)

```bash
cp .env.example .env
# .env içinde SECRET_KEY ve ALLOWED_HOSTS'u ayarlayın
docker compose up --build
```

Uygulama: http://localhost:8000  
Admin: http://localhost:8000/admin/  
Health: http://localhost:8000/health/

İlk admin kullanıcısı: `docker compose exec web python manage.py createsuperuser`

## Proje yapısı

- `config/` – Django proje ayarları (settings/base, development, production)
- `config/urls.py` – URL yapılandırması
- `templates/` – Şablonlar
- `Dockerfile` – Çok aşamalı production image
- `docker-compose.yml` – web (Gunicorn) + PostgreSQL
- `entrypoint.sh` – Migrate + collectstatic sonrası Gunicorn

## Ortam değişkenleri (.env)

| Değişken | Açıklama |
|----------|----------|
| SECRET_KEY | Django secret key (production’da mutlaka değiştirin) |
| DEBUG | True/False |
| ALLOWED_HOSTS | Virgülle ayrılmış host listesi |
| POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD | Docker Compose PostgreSQL |
| CORS_ALLOWED_ORIGINS, CSRF_TRUSTED_ORIGINS | CORS/CSRF için origin listesi |
