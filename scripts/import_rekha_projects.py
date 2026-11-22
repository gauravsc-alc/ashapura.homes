#!/usr/bin/env python3
"""
import_rekha_projects.py — Import Rekha SketchUp renders as portfolio projects.

Copies real design renders from the external sketchup folder into
`static/images/projects/`, converts them to optimised JPEG, and merges the
result into `content/portfolio.json` as new projects.

Source images are read-only and never modified.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\import_rekha_projects.py --source "<path>"
    .\\.venv\\Scripts\\python.exe scripts\\import_rekha_projects.py --source "<path>" --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_PATH = REPO_ROOT / "content" / "portfolio.json"
OUTPUT_ROOT = REPO_ROOT / "static" / "images" / "projects"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SKIP_DIR_NAMES = {"vfb_history", "__pycache__", "ies-lights-pack", ".git"}

MAX_DIMENSION = 1920
JPEG_QUALITY = 85

# ── Project mapping ─────────────────────────────────────────
# Only real client projects are imported. Software installers, lighting-IES
# reference libraries and material swatch folders are excluded on purpose.
#
#   key            = project id + slug used in the site
#   source_folder  = folder inside the sketchup root
#   rooms          = { source sub-folder : display title }
#
# Material swatches ("wall paper", "laminates kids room") and the IES lighting
# library are reference material, not renders, so they are not published.
PROJECT_MAP = [
    {
        "id": "mujeet-sir",
        "slug": "project-6",
        "order": 6,
        "title": "Project 6",
        "source_folder": "MUJEET SIR",
        "description": (
            "A complete residence scheme — living hall, terrace, master bedroom, "
            "kids bedroom, parent room, kitchen and study, explored space by space."
        ),
        "exclude_dirs": ["wall paper", "laminates kids room"],
        "rooms": {
            "LIVING HALL": "Living Hall",
            "TERRACE": "Terrace",
            "master bedroom": "Master Bedroom",
            "New folder (2)": "Kids Bedroom",
            "New folder (4)": "Parent Room & Study",
            "New folder": "Parent Room",
            "1": "Kitchen & Living",
            "2d drawings": "2D Drawings",
            "REKHA": "Terrace & Living Hall",
            "": "Exterior & Overview",
        },
    },
    {
        "id": "rashmi",
        "slug": "project-7",
        "order": 7,
        "title": "Project 7",
        "source_folder": "RASHMI",
        "description": (
            "Bedroom joinery, wardrobe detailing, TV unit and study nook "
            "designs developed around warm wood and fluted finishes."
        ),
        "exclude_dirs": [],
        "rooms": {
            "rashmi": "Bedroom & TV Unit",
            "New folder": "Living Hall",
            "New folder (2)": "Overview",
            "tv unit images": "TV Unit",
            "": "Overview",
        },
    },
    {
        "id": "jaspal-ji",
        "slug": "project-8",
        "order": 8,
        "title": "Project 8",
        "source_folder": "jaspal ji",
        "description": (
            "Bedroom layout study with wardrobe placement and bed-back "
            "detailing explored from multiple angles."
        ),
        "exclude_dirs": [],
        "rooms": {
            "": "Bedroom",
        },
    },
    {
        "id": "project-10",
        "slug": "project-9",
        "order": 9,
        "title": "Project 9",
        "source_folder": "New folder (3)",
        "description": (
            "Kids bedroom study in an ocean-themed scheme with a study desk, "
            "dressing unit and wardrobe elevation."
        ),
        "exclude_dirs": [],
        "rooms": {
            "": "Kids Bedroom",
        },
    },
]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def title_case(value: str) -> str:
    text = re.sub(r"[_\.]+", " ", value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.title()


def path_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def collect_images(folder: Path, exclude_dirs: list[str] | None = None) -> list[tuple[Path, str]]:
    """Return (file, relative-path-within-project) for every usable image."""
    excluded = {name.lower() for name in (exclude_dirs or [])}
    found: list[tuple[Path, str]] = []
    for file_path in sorted(folder.rglob("*"), key=lambda p: str(p).lower()):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        relative = file_path.relative_to(folder)
        if any(part.lower() in SKIP_DIR_NAMES for part in relative.parts):
            continue
        if any(part.lower() in excluded for part in relative.parts):
            continue
        found.append((file_path, relative.as_posix()))
    return found


def convert_to_jpeg(source: Path, target: Path) -> tuple[int, int]:
    """Convert to an optimised JPEG, honouring EXIF orientation."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        scale = min(1.0, MAX_DIMENSION / max(image.width, image.height))
        width = max(1, round(image.width * scale))
        height = max(1, round(image.height * scale))
        resized = image.resize((width, height), Image.LANCZOS)
        resized.save(target, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return width, height


def build_room_title(source_folder: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    if not source_folder:
        return "Project Overview"
    return title_case(source_folder)


def import_project(spec: dict, source_root: Path, dry_run: bool) -> dict | None:
    project_source = source_root / spec["source_folder"]
    if not project_source.is_dir():
        print(f"  ! missing source folder: {project_source}")
        return None

    images = collect_images(project_source, spec.get("exclude_dirs"))
    if not images:
        print(f"  ! no images found in {spec['source_folder']}")
        return None

    project_id = spec["id"]
    rooms: dict[str, dict] = {}
    room_order: list[str] = []
    seen_digests: dict[str, str] = {}
    duplicates = 0

    for file_path, relative in images:
        room_source = ""
        if "/" in relative:
            room_source = relative.rsplit("/", 1)[0]
            # Keep only the first level as the room key.
            room_source = room_source.split("/")[0]

        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if digest in seen_digests:
            duplicates += 1
            continue
        seen_digests[digest] = relative

        if room_source not in rooms:
            room_id = "overview" if not room_source else f"{slugify(room_source)}-{path_hash(room_source)}"
            rooms[room_source] = {
                "id": room_id,
                "title": build_room_title(room_source, spec["rooms"].get(room_source)),
                "source_folder": room_source,
                "images": [],
            }
            room_order.append(room_source)

        stem = slugify(file_path.stem)[:70]
        file_name = f"{stem}-{path_hash(relative)}.jpg"
        image_path = f"images/projects/{project_id}/{rooms[room_source]['id']}/{file_name}"

        if not dry_run:
            width, height = convert_to_jpeg(file_path, OUTPUT_ROOT / project_id / rooms[room_source]["id"] / file_name)
        else:
            with Image.open(file_path) as probe:
                width, height = probe.size

        title = title_case(file_path.stem)
        if re.fullmatch(r"[\d\s]+", file_path.stem) or file_path.stem.lower().startswith(("unnamed", "screenshot")):
            title = f"{rooms[room_source]['title']} — View {len(rooms[room_source]['images']) + 1}"

        rooms[room_source]["images"].append({
            "image": image_path,
            "title": title,
            "source": relative,
            "width": width,
            "height": height,
        })

    room_list = [rooms[key] for key in room_order]
    all_images = [img for room in room_list for img in room["images"]]
    if not all_images:
        print(f"  ! {spec['source_folder']} produced no publishable images")
        return None

    # Prefer a living-hall style image as the cover.
    cover = all_images[0]["image"]
    for img in all_images:
        if re.search(r"living hall|hall tv|family sitting", img["source"], re.I):
            cover = img["image"]
            break

    project = {
        "id": project_id,
        "source_folder": spec["source_folder"],
        "title": spec["title"],
        "slug": spec["slug"],
        "order": spec["order"],
        "description": spec["description"],
        "enabled": True,
        "cover": cover,
        "image_count": len(all_images),
        "rooms": room_list,
    }
    print(f"  + {spec['source_folder']}: {len(all_images)} images in {len(room_list)} rooms "
          f"({duplicates} duplicates skipped)")
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Rekha SketchUp renders as portfolio projects.")
    parser.add_argument("--source", required=True, help="Path to the sketchup source root")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be imported")
    args = parser.parse_args()

    source_root = Path(args.source).expanduser()
    if not source_root.is_dir():
        print(f"Source root not found: {source_root}")
        return 1

    if not CONTENT_PATH.exists():
        print(f"Portfolio content file not found: {CONTENT_PATH}")
        return 1

    existing = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))

    print(f"Importing from {source_root} (dry_run={args.dry_run})")
    imported: list[dict] = []
    for spec in PROJECT_MAP:
        project = import_project(spec, source_root, args.dry_run)
        if project:
            imported.append(project)

    if not imported:
        print("Nothing to import.")
        return 1

    # Merge: replace a project with the same id, otherwise append.
    by_id = {p["id"]: p for p in existing}
    for project in imported:
        by_id[project["id"]] = project
    merged = sorted(by_id.values(), key=lambda p: (p.get("order", 999), p["id"]))

    if not args.dry_run:
        CONTENT_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Updated {CONTENT_PATH.name} -> {len(merged)} projects")

    total = sum(p["image_count"] for p in imported)
    print(f"Done. {len(imported)} project(s), {total} images imported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
