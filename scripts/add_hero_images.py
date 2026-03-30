#!/usr/bin/env python3
"""
add_hero_images.py  —  AI Newsletter Hero Image Generator
========================================================
Reads an AI Newsflash HTML file, generates an Imagen 4 cinematic hero
image for every news card, embeds them as a full-width banner strip,
and saves the result as a new HTML file.

Usage:
    python add_hero_images.py --input ai-newsflash-march-25-2026.html

    # Preview without spending API credits:
    python add_hero_images.py --input ai-newsflash-march-25-2026.html --dry-run

Requirements:
    pip install google-genai beautifulsoup4
    Set GEMINI_API_KEY environment variable before running.
    (Requires a billing-enabled Google AI Studio key)
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from google import genai
from google.genai import types

sys.stdout.reconfigure(encoding="utf-8")

# ── CONFIG ────────────────────────────────────────────────────────────────────
IMAGE_DIR   = "images"     # subfolder next to the output HTML
ASPECT      = "16:9"       # Imagen 4 aspect ratio for hero banners
DELAY_SEC   = 3            # pause between API calls (rate-limit safety)

# Visual style prefix prepended to every prompt
STYLE_PREFIX = (
    "Cinematic dark-tech visualization. Deep black background. Dramatic neon "
    "accent lighting. Ultra-detailed, photorealistic, wide 16:9 composition. "
    "NO text, NO words, NO letters, NO UI elements, NO logos. Subject: "
)

# ── CSS injected into the output HTML ────────────────────────────────────────
HERO_CSS = """
    /* ── HERO IMAGE STRIP ────────────────────────────────────────────── */
    .card.has-hero {
      grid-template-columns: 1fr;
      padding-top: 0;
    }
    .card-hero {
      grid-column: 1 / -1;
      grid-row: 1;
      position: relative;
      height: 165px;
      overflow: hidden;
      border-radius: var(--radius) var(--radius) 0 0;
      margin-bottom: 16px;
    }
    .card-hero > img {
      width: 100%; height: 100%;
      object-fit: cover;
      display: block;
      transition: transform 0.45s ease;
    }
    .card:hover .card-hero > img { transform: scale(1.04); }
    /* gradient fade hero → card body */
    .card-hero::after {
      content: '';
      position: absolute; inset: 0;
      background: linear-gradient(to bottom, transparent 45%, var(--surface) 100%);
      pointer-events: none;
    }
    /* logo badge overlaid bottom-right of hero */
    .card-hero-logo {
      position: absolute; bottom: 10px; right: 12px; z-index: 2;
      width: 38px; height: 38px; border-radius: 10px;
      background: rgba(8,8,14,0.80);
      border: 1px solid rgba(255,255,255,0.14);
      display: flex; align-items: center; justify-content: center;
      overflow: hidden; backdrop-filter: blur(10px);
    }
    .card-hero-logo img { width: 26px; height: 26px; object-fit: contain; border-radius: 4px; }
    .card-hero-logo .logo-fallback { font-size: 20px; line-height: 1; }
    /* hide the old logo column when hero is present */
    .card.has-hero > .card-logo { display: none; }
    /* grid row shifts — standard card */
    .card.has-hero .card-headline { grid-row: 2; }
    .card.has-hero .card-what     { grid-row: 3; }
    .card.has-hero .card-why      { grid-row: 4; }
    .card.has-hero .card-footer   { grid-row: 5; }
    /* grid row shifts — card with a tag (date-tag / gossip-tag) */
    .card.has-hero.has-tag .gossip-tag,
    .card.has-hero.has-tag .date-tag  { grid-row: 2; }
    .card.has-hero.has-tag .card-headline { grid-row: 3; }
    .card.has-hero.has-tag .card-what     { grid-row: 4; }
    .card.has-hero.has-tag .card-why      { grid-row: 5; }
    .card.has-hero.has-tag .card-footer   { grid-row: 6; }
"""


# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_section_name(card: Tag) -> str:
    """Return the section title the card lives in (e.g. 'Big Moves')."""
    section = card.find_parent("section")
    if section:
        title = section.find(class_="section-title")
        if title:
            return title.get_text(strip=True)
    return "AI"


def get_company_name(card: Tag) -> str:
    """Return company name from the card-logo img alt attribute, if present."""
    logo_div = card.find(class_="card-logo")
    if logo_div:
        img = logo_div.find("img")
        if img and img.get("alt"):
            return img["alt"]
    return ""


def build_prompt(card: Tag) -> str:
    """Compose a DALL-E 3 prompt from the card's content."""
    section  = get_section_name(card)
    company  = get_company_name(card)
    headline = card.find(class_="card-headline")
    what     = card.find(class_="card-what")

    headline_text = headline.get_text(strip=True) if headline else ""
    what_text     = what.get_text(strip=True)[:180] if what else ""

    # Build a natural-language theme description
    parts = []
    if company:
        parts.append(f"a scene representing {company}")
    if headline_text:
        parts.append(headline_text)
    if what_text:
        parts.append(what_text)
    if section:
        parts.append(f"(context: {section})")

    theme = ". ".join(parts)
    return STYLE_PREFIX + theme


def extract_logo_inner_html(card: Tag) -> str:
    """Return the inner HTML of card-logo to reuse inside the hero badge."""
    logo_div = card.find(class_="card-logo")
    return logo_div.decode_contents() if logo_div else '<span class="logo-fallback">🤖</span>'


def safe_filename(text: str, index: int) -> str:
    cleaned = re.sub(r"[^\w]", "_", text)[:48].strip("_")
    return f"hero_{index:02d}_{cleaned}.jpg"


# ── MAIN PROCESSING ───────────────────────────────────────────────────────────

def process(input_path: Path, output_path: Path, client, dry_run: bool) -> None:
    html = input_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # Inject hero CSS before </style>
    style_tag = soup.find("style")
    if style_tag:
        existing = style_tag.string or ""
        style_tag.string = existing + HERO_CSS
    else:
        print("WARNING: No <style> tag found — CSS not injected.")

    # Ensure images directory exists next to the output file
    img_dir = output_path.parent / IMAGE_DIR
    img_dir.mkdir(exist_ok=True)

    cards = soup.find_all(class_="card")
    total = len(cards)
    print(f"\nFound {total} cards to process.\n")

    for i, card in enumerate(cards, 1):
        headline_el  = card.find(class_="card-headline")
        headline_txt = headline_el.get_text(strip=True) if headline_el else f"card {i}"
        print(f"[{i:02d}/{total}] {headline_txt[:65]}")

        img_filename   = safe_filename(headline_txt, i)
        img_local_path = img_dir / img_filename
        img_html_src   = f"{IMAGE_DIR}/{img_filename}"

        if dry_run:
            # Placeholder — a dark gradient rectangle (no API call)
            color = ["0a0a0f/00D4FF", "0a0a0f/FF006E", "0a0a0f/00FF9D", "0a0a0f/FFD60A"][i % 4]
            img_html_src = f"https://placehold.co/1792x1024/{color}?text=HERO+{i}"
            print(f"         dry-run placeholder -> {img_html_src}")
        else:
            prompt = build_prompt(card)
            print(f"         prompt  -> {prompt[:90]}...")
            try:
                response = client.models.generate_images(
                    model="imagen-4.0-generate-001",
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio=ASPECT,
                        output_mime_type="image/jpeg",
                        safety_filter_level="BLOCK_LOW_AND_ABOVE",
                    ),
                )
                if not response.generated_images:
                    print(f"         WARNING: no image returned — skipping")
                    continue
                image_bytes = response.generated_images[0].image.image_bytes
                img_local_path.write_bytes(image_bytes)
                print(f"         saved   -> {img_local_path} ({len(image_bytes)//1024} KB)")
            except Exception as exc:
                print(f"         ERROR: {exc} — skipping")
                continue

            if i < total:
                time.sleep(DELAY_SEC)

        # ── Inject hero div as first child of card ────────────────────────
        logo_inner = extract_logo_inner_html(card)
        hero_html = (
            f'<div class="card-hero">'
            f'<img src="{img_html_src}" alt="" loading="lazy">'
            f'<div class="card-hero-logo">{logo_inner}</div>'
            f'</div>'
        )
        hero_fragment = BeautifulSoup(hero_html, "html.parser")
        card.insert(0, hero_fragment)

        # Add has-hero class
        classes = card.get("class", [])
        if "has-hero" not in classes:
            card["class"] = classes + ["has-hero"]

    output_path.write_text(str(soup), encoding="utf-8")
    print(f"\nDone! Output -> {output_path}")
    if not dry_run:
        print(f"  Images  -> {img_dir}/")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Add Imagen 4 hero images to an AI Newsflash HTML newsletter."
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to the newsletter HTML file (e.g. ai-newsflash-march-25-2026.html)"
    )
    parser.add_argument(
        "--output",
        help="Output path (default: <input_stem>_with_images.html in same folder)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Imagen API calls and use placeholder images instead"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: file not found: {input_path}")

    output_path = (
        Path(args.output) if args.output
        else input_path.with_stem(input_path.stem + "_with_images")
    )

    # Resolve API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        sys.exit(
            "Error: GEMINI_API_KEY environment variable not set.\n"
            "       Run:  set GEMINI_API_KEY=AIza...  (Windows CMD)\n"
            "         or: $env:GEMINI_API_KEY='AIza...'  (PowerShell)\n"
            "       Or use --dry-run to test without API calls."
        )

    client = genai.Client(api_key=api_key) if api_key else None
    process(input_path, output_path, client, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
