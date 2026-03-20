# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Setup

This project runs via Docker. Start it with:

```bash
./start.sh          # builds image and runs docker-compose
docker compose up   # if image already built
```

**Database migrations:**
```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

**Load fixture data:**
```bash
python manage.py loaddata fixture.json
```

Configuration is via `.env` file (database, AWS credentials, Django secret key).

There is no automated test suite or linter configured.

## Architecture Overview

Personal portfolio app built on **Django 6 + Wagtail CMS**. PostgreSQL 18 for data, AWS S3 for media in production (falls back to filesystem if no bucket configured), WhiteNoise with Brotli for static files.

### Apps

- **nicolabeirer** — project root; home view aggregates recent blog posts, adventures, and projects; root URL routing
- **blog** — Wagtail `BlogIndexPage` / `BlogPage` with `StreamField` body (HeadingBlock, ImageBlock, CodeBlock, QuoteBlock); taggit for tags
- **adventures** — Activity tracking with FIT/GPX file parsing; `AdventurePage` has orderable `ActivityFile` and `Waypoint` children; `services.py` parses uploaded files into stats + GeoJSON; `signals.py` triggers processing in a daemon thread on page publish
- **projects** — Simple `ResumeProject` model (JSON fields for features/keywords/links); admin-managed only
- **resume** — Wagtail `ResumePage` with structured StreamField blocks (WorkExperienceBlock, EducationBlock, SkillGroupBlock, etc.)

### Key Patterns

- **Wagtail pages** inherit from `Page` and use `StreamField` for flexible block-based content. Each block type has a matching template in `templates/<app>/blocks/`.
- **Background file processing**: page publish signal → daemon thread → `adventures/services.py` parses FIT/GPX → saves stats JSON and route GeoJSON back onto the model. Not using Celery — plain threads.
- **Media storage** is conditional: S3 if `AWS_STORAGE_BUCKET_NAME` is set, otherwise local `MEDIA_ROOT`.
- **Custom template filter** `duration` in `adventures/templatetags/` formats seconds → "Xh MMm".
