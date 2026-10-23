# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Setup

This project runs via Docker. Start it with:

```bash
./dev.sh            # development: source mount and Django auto-reload
./dev.sh -d         # start the same stack in the background
./start.sh          # builds image and runs docker-compose
docker compose up   # if image already built
```

The development overlay uses the existing PostgreSQL volume, mounts this
checkout at `/app`, and runs Django's development server. Python, template,
CSS, and JavaScript edits are picked up without rebuilding the image. Changes
to `pyproject.toml` or `uv.lock` need another `./dev.sh` to rebuild dependencies.
The development media volume persists local uploads when S3 media storage is
disabled.

For host Python commands, install dependencies with `uv sync --locked`, then
load `.env` and point at the published database port, for example:
`POSTGRES_HOST=localhost uv run --locked --env-file .env python manage.py test`.

**Database migrations:**
```bash
POSTGRES_HOST=localhost uv run --locked --env-file .env python manage.py migrate --noinput
POSTGRES_HOST=localhost uv run --locked --env-file .env python manage.py collectstatic --noinput
```

Configuration is via `.env` file (database, AWS credentials, Django secret key).

The test suite runs with `python manage.py test` in the dev container or with
the host command above.

## Architecture Overview

Personal portfolio app built on **Django 6 + Wagtail CMS**. PostgreSQL 18 for data, AWS S3 for media in production (falls back to filesystem if no bucket configured), WhiteNoise with Brotli for static files.

### Apps

- **nicolabeirer** — project root; home view and root URL routing
- **blog** — Wagtail `BlogIndexPage` / `BlogPage` with `StreamField` body (HeadingBlock, ImageBlock, CodeBlock, QuoteBlock); taggit for tags
- **adventures** — Routes own FIT/GPX recordings, statistics, and geometry; `AdventurePage` selects routes or route groups and holds story content
- **projects** — Simple `ResumeProject` model (JSON fields for features/keywords/links); admin-managed only
- **resume** — Wagtail `ResumePage` with structured StreamField blocks (WorkExperienceBlock, EducationBlock, SkillGroupBlock, etc.)

### Key Patterns

- **Wagtail pages** inherit from `Page` and use `StreamField` for flexible block-based content. Each block type has a matching template in `templates/<app>/blocks/`.
- **Route processing**: saving a new or replaced recording parses its FIT/GPX file and stores stats and GeoJSON on the route, outside Wagtail page revisions.
- **Media storage** is conditional: S3 if `AWS_STORAGE_BUCKET_NAME` is set, otherwise local `MEDIA_ROOT`.
- **Custom template filter** `duration` in `adventures/templatetags/` formats seconds → "Xh MMm".
