# Generated migration for YouTubeTranscript

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="YouTubeTranscript",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("video_url", models.URLField()),
                ("video_id", models.CharField(max_length=50)),
                ("title", models.CharField(blank=True, max_length=255, null=True)),
                ("raw_text", models.TextField(null=True)),
                ("clean_text", models.TextField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "YouTube Transkript",
                "verbose_name_plural": "YouTube Transkriptler",
                "ordering": ["-created_at"],
            },
        ),
    ]
