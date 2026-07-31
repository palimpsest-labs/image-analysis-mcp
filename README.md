# image-analysis-mcp

FastMCP server for image analysis — OCR, metadata, and EXIF extraction. Part of the [Palimpsest](https://github.com/palimpsest-labs/palimpsest) intelligence toolkit.

## Why

LLMs can't see images natively. This server fills the gap — extract text from screenshots, photos, and diagrams via OCR, pull EXIF camera data and GPS coordinates, and get full image metadata (format, dimensions, DPI, color space). All results are returned as structured JSON for easy downstream processing.

## Architecture

Pluggable OCR backends with graceful degradation:

* **base install** (`pip install image-analysis-mcp`) — metadata / EXIF only (Pillow + exifread, ~5 MB)
* **with OCR** (`pip install image-analysis-mcp[ocr]`) — adds rapidocr-onnxruntime (~250 MB)
* **with Tesseract** (`pip install image-analysis-mcp[tesseract]`) — adds pytesseract (needs system `tesseract-ocr`)

The server tries backends in priority order: rapidocr → tesseract → none.

## Tools

| Tool | Description |
|---|---|
| `ocr_image(image_path)` | OCR text from an image — returns text blocks with confidence scores and bounding boxes |
| `image_metadata(path)` | Full metadata: file info, image dimensions, EXIF tags, GPS coordinates |
| `extract_text(image_path)` | Convenience wrapper — OCR + metadata combined in one response |

## Installation

```bash
git clone https://github.com/palimpsest-labs/image-analysis-mcp
cd image-analysis-mcp
python3 -m venv .venv
source .venv/bin/activate

# Minimal (metadata only)
pip install -e .

# With OCR support
pip install -e ".[ocr]"

# With Tesseract support (requires system tesseract-ocr)
pip install -e ".[tesseract]"
```

## Usage

```python
from image_analysis_mcp.server import extract_text, image_metadata, ocr_image

# Get everything at once
result = extract_text("~/screenshots/page.png")

# Or separate calls
meta = image_metadata("~/screenshots/page.png")
text = ocr_image("~/screenshots/page.png")
```

## Security

Paths must be absolute and resolve to a location under the user's home directory. Path traversal (`..`) and paths starting with `/` are rejected. Symlinks are resolved before checking home-directory containment.

## License

MIT
