"""
Import Instagram exports into the Gallery app.

Reads two extracted Instagram archives (personal + travel accounts) and
creates one GalleryAlbumPage per year, uploading each image to Wagtail's
image library (and therefore to S3 when AWS_STORAGE_BUCKET_NAME is set).

Usage:
    python manage.py import_meta_photos --exports-dir /path/to/meta-exports
    python manage.py import_meta_photos --exports-dir /path/to/meta-exports --dry-run
    python manage.py import_meta_photos --exports-dir /path/to/meta-exports --limit 10

The command is fully idempotent: re-running it skips already-imported photos
by matching on Wagtail Image file_hash (SHA-1).
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from django.core.files.images import ImageFile
from django.core.management.base import BaseCommand, CommandError
from wagtail.images import get_image_model


# Instagram exports double-encode non-ASCII text as latin-1 bytes interpreted
# as UTF-8 codepoints. This fixes captions like "ð¤" back to real emoji.
def _fix_encoding(s):
    if not s:
        return s
    try:
        return s.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

# Known subpaths for the two accounts' archives
ACCOUNT_ROOTS = [
    "instagram-nicolabeirer-2026-03-19-ExtRPck7",  # personal
    "instagram-nicolab.traveling-2026-03-19-nHleBHSA",  # travel
]


def _find_account_roots(exports_dir: Path):
    """Walk exports_dir one level deep and return matching account dirs."""
    roots = []
    for name in ACCOUNT_ROOTS:
        # Could be directly inside exports_dir or one folder deep
        direct = exports_dir / name
        if direct.is_dir():
            roots.append(direct)
            continue
        for child in exports_dir.iterdir():
            if child.is_dir() and (child / name).is_dir():
                roots.append(child / name)
                break
    return roots


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_items(account_root: Path):
    """
    Returns a list of dicts:
        {path: Path, caption: str, timestamp: int}
    for all image files in posts/ and stories/ of this account root.
    """
    items = []
    meta_dir = account_root / "your_instagram_activity" / "media"

    # --- posts ---
    posts_json = meta_dir / "posts_1.json"
    if posts_json.exists():
        with open(posts_json) as f:
            posts = json.load(f)
        for post in posts:
            caption = _fix_encoding(post.get("title") or "")
            for media in post.get("media", []):
                uri = media.get("uri", "")
                ts = media.get("creation_timestamp") or post.get("creation_timestamp", 0)
                file_path = account_root / uri
                if not file_path.exists():
                    continue
                if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                items.append({"path": file_path, "caption": caption, "timestamp": ts})

    # --- stories ---
    stories_json = meta_dir / "stories.json"
    if stories_json.exists():
        with open(stories_json) as f:
            data = json.load(f)
        story_list = data.get("ig_stories", data) if isinstance(data, dict) else data
        for story in story_list:
            uri = story.get("uri", "")
            ts = story.get("creation_timestamp", 0)
            caption = _fix_encoding(story.get("title") or "")
            file_path = account_root / uri
            if not file_path.exists():
                continue
            if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            items.append({"path": file_path, "caption": caption, "timestamp": ts})

    return items


class Command(BaseCommand):
    help = "Import Instagram meta-export photos into Gallery albums, one album per year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--exports-dir",
            required=True,
            help="Path to the directory containing the extracted Instagram export folders.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be imported without touching the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after importing this many photos (0 = no limit). Useful for smoke tests.",
        )

    def handle(self, *args, **options):
        exports_dir = Path(options["exports_dir"])
        dry_run = options["dry_run"]
        limit = options["limit"]

        if not exports_dir.is_dir():
            raise CommandError(f"exports-dir does not exist: {exports_dir}")

        # Import here to avoid issues when app registry isn't ready
        from wagtail.models import Page, Site

        from gallery.models import GalleryAlbumPage, GalleryIndexPage, GalleryPhoto

        Image = get_image_model()

        # ------------------------------------------------------------------ #
        # 1. Collect all image items from both accounts                       #
        # ------------------------------------------------------------------ #
        account_roots = _find_account_roots(exports_dir)
        if not account_roots:
            # Fall back: try to find any dir with posts_1.json
            for d in exports_dir.rglob("posts_1.json"):
                candidate = d.parent.parent.parent.parent  # up from .../your_instagram_activity/media/posts_1.json
                if candidate.is_dir() and candidate not in account_roots:
                    account_roots.append(candidate)

        if not account_roots:
            raise CommandError(
                f"No recognised Instagram export folders found under {exports_dir}.\n"
                "Expected subfolders: " + ", ".join(ACCOUNT_ROOTS)
            )

        self.stdout.write(f"Found {len(account_roots)} account root(s):")
        for r in account_roots:
            self.stdout.write(f"  {r.name}")

        all_items = []
        for root in account_roots:
            items = _collect_items(root)
            self.stdout.write(f"  {root.name}: {len(items)} images found")
            all_items.extend(items)

        # Group by year
        by_year: dict[int, list] = {}
        for item in all_items:
            ts = item["timestamp"]
            year = datetime.fromtimestamp(ts, tz=timezone.utc).year if ts else 0
            by_year.setdefault(year, []).append(item)

        # Sort within each year by timestamp ascending
        for year in by_year:
            by_year[year].sort(key=lambda x: x["timestamp"])

        self.stdout.write(f"\nYears found: {sorted(by_year.keys())}")
        for year in sorted(by_year.keys()):
            self.stdout.write(f"  {year}: {len(by_year[year])} photos")

        total_to_import = sum(len(v) for v in by_year.values())
        if limit:
            self.stdout.write(f"\n--limit {limit}: will stop after {limit} photos")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[dry-run] No changes written."))
            return

        # ------------------------------------------------------------------ #
        # 2. Ensure GalleryIndexPage exists                                   #
        # ------------------------------------------------------------------ #
        gallery_index = GalleryIndexPage.objects.first()
        if not gallery_index:
            self.stdout.write("No GalleryIndexPage found — creating one under the root page...")
            root_page = Page.objects.filter(depth=1).first()
            home_page = Page.objects.filter(depth=2).first() or root_page
            gallery_index = GalleryIndexPage(
                title="Gallery",
                slug="gallery",
                intro="",
            )
            home_page.add_child(instance=gallery_index)
            gallery_index.save_revision().publish()
            self.stdout.write(self.style.SUCCESS("  Created GalleryIndexPage at /gallery/"))

        # ------------------------------------------------------------------ #
        # 3. Import photos                                                    #
        # ------------------------------------------------------------------ #
        stats = {"added": 0, "dup": 0, "error": 0, "albums_created": 0, "albums_updated": 0}
        imported_count = 0

        for year in sorted(by_year.keys()):
            items = by_year[year]
            year_added = 0
            year_dup = 0

            # --- Get or create the album page ---
            slug = str(year)
            existing_album = GalleryAlbumPage.objects.child_of(gallery_index).filter(slug=slug).first()
            if existing_album:
                album = existing_album
                stats["albums_updated"] += 1
            else:
                earliest_ts = items[0]["timestamp"]
                album_date = datetime.fromtimestamp(earliest_ts, tz=timezone.utc).date()
                album = GalleryAlbumPage(
                    title=f"{year}!",
                    slug=slug,
                    date=album_date,
                )
                gallery_index.add_child(instance=album)
                stats["albums_created"] += 1
                self.stdout.write(f"\nCreated album: {year}!")

            # --- Import each photo ---
            for item in items:
                if limit and imported_count >= limit:
                    break

                file_path: Path = item["path"]
                caption: str = item["caption"]
                ts: int = item["timestamp"]

                try:
                    file_hash = _sha1(file_path)
                except OSError as e:
                    self.stderr.write(f"  Cannot read {file_path}: {e}")
                    stats["error"] += 1
                    continue

                # Dedup by hash
                existing_image = Image.objects.filter(file_hash=file_hash).first()
                if existing_image:
                    image = existing_image
                    stats["dup"] += 1
                    year_dup += 1
                else:
                    title = caption[:200] if caption else file_path.stem
                    try:
                        with open(file_path, "rb") as f:
                            image = Image(title=title or file_path.stem)
                            image.file = ImageFile(f, name=file_path.name)
                            image._set_image_file_metadata()
                            image.save()
                    except Exception as e:
                        self.stderr.write(f"  Failed to upload {file_path.name}: {e}")
                        stats["error"] += 1
                        continue
                    stats["added"] += 1
                    year_added += 1

                # Link photo to album (idempotent)
                date_taken = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
                _, created = GalleryPhoto.objects.get_or_create(
                    page=album,
                    image=image,
                    defaults={"caption": caption, "date_taken": date_taken},
                )

                imported_count += 1

            # Set cover image to newest photo if not already set
            if not album.cover_image:
                last_photo = GalleryPhoto.objects.filter(page=album).order_by("-date_taken").first()
                if last_photo:
                    album.cover_image = last_photo.image

            # Rebuild sort_order by date_taken ascending
            photos = list(GalleryPhoto.objects.filter(page=album).order_by("date_taken"))
            for i, photo in enumerate(photos):
                if photo.sort_order != i:
                    GalleryPhoto.objects.filter(pk=photo.pk).update(sort_order=i)

            album.save()
            album.save_revision().publish()

            self.stdout.write(
                f"  {year}: {year_added} new, {year_dup} already present"
            )

            if limit and imported_count >= limit:
                self.stdout.write(self.style.WARNING(f"\nStopped at --limit {limit}."))
                break

        # ------------------------------------------------------------------ #
        # 4. Summary                                                          #
        # ------------------------------------------------------------------ #
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(
            f"Done. Albums created: {stats['albums_created']}  updated: {stats['albums_updated']}\n"
            f"      Images uploaded: {stats['added']}  already present: {stats['dup']}  errors: {stats['error']}"
        ))
