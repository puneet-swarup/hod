"""
Build the printable training manual: Markdown guides -> one PDF.

    python scripts/build_training_pdf.py

Reads the guides in docs/training/, renders them to a single HTML document
with a cover, a table of contents and print styling, then asks headless
Chromium to print it to docs/training/House-of-Desserts-Training-Manual.pdf.

Requirements: `markdown` (pip), and a Chromium/Chrome binary. On Debian the
binary is usually `chromium` or `chromium-browser`; set CHROME=/path/to/bin
to override.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover - developer convenience
    sys.exit("This script needs the 'markdown' package: pip install markdown")

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("This script needs Pillow: pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
TRAINING = ROOT / "docs" / "training"
OUTPUT = TRAINING / "House-of-Desserts-Training-Manual.pdf"

# Order matters: this is the reading order of the printed manual.
GUIDES = [
    ("screen-tour.md", "Screen tour: every tab in the app"),
    ("retail-orders.md", "Retail: customers and orders"),
    ("products-and-inventory.md", "Products, recipes and inventory"),
    ("b2b-partners.md", "Selling to shops and franchisees"),
    ("reports-and-export.md", "Reports, export and the audit trail"),
    ("routines.md", "Daily and monthly routines"),
]

CSS = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Noto Sans", "DejaVu Sans", Arial, sans-serif;
  font-size: 10.5pt; line-height: 1.55; color: #26211c; margin: 0;
}
h1 { font-size: 20pt; color: #7c2d12; margin: 0 0 4pt; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 13.5pt; color: #92400e; margin: 18pt 0 6pt; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #7c2d12; margin: 13pt 0 4pt; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { margin: 4pt 0 8pt 16pt; padding: 0; }
li { margin-bottom: 2pt; }
code {
  font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
  background: #f5f0e8; padding: 0.5pt 3pt; border-radius: 3px;
}
pre { background: #f5f0e8; padding: 8pt; border-radius: 4px; overflow: auto; font-size: 9pt; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; font-size: 9.5pt; }
th, td { border: 0.5pt solid #d6cec1; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #faf5ec; color: #7c2d12; }
blockquote {
  margin: 8pt 0; padding: 6pt 10pt; background: #fdf6e7;
  border-left: 3pt solid #d97706; font-size: 10pt;
}
blockquote p { margin: 0; }
img {
  max-width: 100%; max-height: 165mm; display: block; margin: 8pt auto 14pt;
  border: 0.5pt solid #e5ded2; page-break-inside: avoid;
}
hr { border: none; border-top: 0.5pt solid #e5ded2; margin: 14pt 0; }
a { color: #92400e; text-decoration: none; }
/* Cover */
.cover { text-align: center; padding-top: 60mm; page-break-after: always; }
.cover h1 { page-break-before: avoid; font-size: 30pt; color: #7c2d12; margin-bottom: 6pt; }
.cover .sub { font-size: 13pt; color: #92400e; margin-bottom: 30pt; }
.cover .meta { font-size: 10pt; color: #6b6154; line-height: 1.9; }
.cover .rule { width: 40mm; height: 2pt; background: #d97706; margin: 16pt auto; }
.toc { page-break-after: always; }
.toc h1 { page-break-before: avoid; }
.toc ol { margin-left: 14pt; }
.toc li { margin-bottom: 6pt; font-size: 11pt; }
"""

COVER = """
<div class="cover">
  <h1>House of Desserts</h1>
  <div class="sub">Training manual</div>
  <div class="rule"></div>
  <div class="meta">
    Orders &middot; Products &amp; inventory &middot; Wholesale partners &middot; Reports<br>
    Written for whoever runs the bakery<br><br>
    {date}
  </div>
</div>
"""


def _strip_title(md_text: str) -> str:
    """Drop the leading '# Title' — the cover and TOC carry the title."""
    lines = md_text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def _strip_toc(md_text: str) -> str:
    """Drop a guide's own '## Contents' block; the manual has one TOC."""
    return re.sub(
        r"^## Contents\n(?:.*\n)*?(?=^## )",
        "",
        md_text,
        flags=re.MULTILINE,
    )


def build_html() -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "attr_list"])

    parts: list[str] = []
    toc_items: list[str] = []

    for idx, (filename, title) in enumerate(GUIDES, start=1):
        path = TRAINING / filename
        if not path.exists():
            sys.exit(f"Missing guide: {path}")
        text = _strip_toc(_strip_title(path.read_text(encoding="utf-8")))
        md.reset()
        body = md.convert(text)
        # Demote headings so each guide's sections sit under one H1.
        body = re.sub(r"<h2>", "<h2>", body)
        parts.append(f'<section class="guide"><h1 id="g{idx}">{title}</h1>{body}</section>')
        toc_items.append(f'<li><a href="#g{idx}">{title}</a></li>')

    from datetime import date

    cover = COVER.format(date=date.today().strftime("%d %B %Y"))
    toc = (
        '<div class="toc"><h1>Contents</h1><ol>'
        + "".join(toc_items)
        + "</ol></div>"
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>House of Desserts — Training Manual</title>"
        f"<style>{CSS}</style></head><body>"
        f"{cover}{toc}{''.join(parts)}"
        "</body></html>"
    )


def prepare_images(src_dir: Path, dst_dir: Path) -> None:
    """Copy screenshots, folding very tall phone captures into columns.

    A full-page phone screenshot is around 1:4, which cannot be printed
    legibly on A4. Slicing it vertically and laying the slices side by side
    keeps the detail and makes the page usable.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    for png in sorted(src_dir.glob("*.png")):
        image = Image.open(png)
        width, height = image.size
        if height <= width * 1.6:
            image.save(dst_dir / png.name)
            continue

        columns = max(2, math.ceil(height / (width * 1.5)))
        slice_height = math.ceil(height / columns)
        gap = max(8, width // 40)
        canvas = Image.new(
            "RGB", (width * columns + gap * (columns - 1), slice_height), "white"
        )
        for i in range(columns):
            box = (0, i * slice_height, width, min((i + 1) * slice_height, height))
            canvas.paste(image.crop(box), (i * (width + gap), 0))
        canvas.save(dst_dir / png.name)


def find_chrome() -> str:
    for name in (os.environ.get("CHROME"), "chromium", "chromium-browser", "google-chrome"):
        if not name:
            continue
        found = shutil.which(name)
        if found:
            return found
    sys.exit("No Chromium/Chrome found. Set CHROME=/path/to/binary.")


def main() -> None:
    html = build_html()

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "manual.html"
        html_path.write_text(html, encoding="utf-8")

        # The images are relative to docs/training/, so copy them next to the
        # HTML rather than rewriting every src.
        shots = TRAINING / "screenshots"
        if shots.is_dir():
            prepare_images(shots, Path(tmp) / "screenshots")

        chrome = find_chrome()
        cmd = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUTPUT}",
            html_path.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"Chromium failed:\n{result.stderr[-2000:]}")

    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({size_kb:.0f} KB)")
    print(f"  {len(GUIDES)} guides, {len(list((TRAINING / 'screenshots').glob('*.png')))} screenshots")


if __name__ == "__main__":
    main()
