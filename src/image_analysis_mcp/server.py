"""image-analysis-mcp MCP server.

Tools:
  ocr_image      — OCR text from an image with confidence scores and bounding boxes
  image_metadata — Full metadata: file info, image dimensions, EXIF tags, GPS
  extract_text   — OCR + metadata combined in one response
"""

import hashlib
import json
import os
import pathlib
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .ocr import get_ocr_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "image-analysis",
    instructions="Analyse images — OCR text extraction, EXIF/metadata reading, and file info extraction",
)

# ---------------------------------------------------------------------------
# Path validation (SSRF / traversal prevention)
# ---------------------------------------------------------------------------


def _resolve_image_path(path: str) -> Optional[str]:
    """Resolve and validate an image path.

    Returns the resolved absolute path string, or None with a descriptive error.
    """
    if not path or path.isspace():
        return None

    path = os.path.expanduser(path)

    # Reject paths starting with /
    if path.startswith("/") and not path.startswith(os.path.expanduser("~")):
        return None

    # Reject path traversal
    if ".." in path.split(os.sep):
        return None

    resolved = pathlib.Path(path).resolve()

    # Must exist
    if not resolved.exists():
        return None

    # Must be a file
    if not resolved.is_file():
        return None

    # Must be under home directory
    home = pathlib.Path.home().resolve()
    try:
        resolved.relative_to(home)
    except ValueError:
        return None

    # Check supported format
    ext = resolved.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        return None

    return str(resolved)


def _validate_path(path: str) -> tuple[Optional[str], Optional[str]]:
    """Validate an image path. Returns (resolved_path, error_message).

    One of the two will be None.
    """
    if not path or path.isspace():
        return None, "Path is empty."

    path = os.path.expanduser(path)

    if path.startswith("/") and not path.startswith(os.path.expanduser("~")):
        return None, "Path must be an absolute path under your home directory."

    if ".." in path.split(os.sep):
        return None, "Path traversal ('..') is not allowed."

    resolved = pathlib.Path(path).resolve()

    if not resolved.exists():
        return None, f"File not found: {path}"

    if not resolved.is_file():
        return None, f"Not a file: {path}"

    # Check home directory containment
    home = pathlib.Path.home().resolve()
    try:
        resolved.relative_to(home)
    except ValueError:
        return None, "Path must be under your home directory."

    ext = resolved.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        return None, (
            f"Unsupported image format '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    return str(resolved), None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _get_image_metadata(image_path: str) -> dict:
    """Extract file and image metadata. Returns a dict with what it can get."""
    result = {}

    # File metadata
    try:
        stat = os.stat(image_path)
        result["file_size"] = stat.st_size
        result["file_created"] = stat.st_ctime
        result["file_modified"] = stat.st_mtime
    except OSError:
        pass

    # SHA-256 hash
    try:
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        result["sha256"] = h.hexdigest()
    except OSError:
        pass

    # Pillow metadata
    try:
        from PIL import Image as PilImage

        with PilImage.open(image_path) as img:
            result["format"] = img.format
            result["mode"] = img.mode
            result["width"] = img.width
            result["height"] = img.height
            if img.info.get("dpi"):
                result["dpi"] = img.info["dpi"]
            if img.info.get("icc_profile"):
                result["icc_profile"] = True
    except ImportError:
        result["_pillow_error"] = "Pillow not available"
    except Exception as e:
        result["_pillow_error"] = str(e)

    # EXIF via exifread
    try:
        import exifread

        with open(image_path, "rb") as f:
            tags = exifread.process_file(f, details=True)

        exif_data = {}
        for tag_name, tag_value in tags.items():
            exif_data[str(tag_name)] = str(tag_value)

        if exif_data:
            result["exif"] = exif_data

        # Extract GPS coordinates
        def _to_decimal(values, ref) -> Optional[float]:
            try:
                d, m, s = [float(v) for v in values.values]
                decimal = d + m / 60.0 + s / 3600.0
                if ref in ("S", "W"):
                    decimal = -decimal
                return decimal
            except (AttributeError, ValueError, TypeError):
                return None

        gps_lat = tags.get("GPS GPSLatitude")
        gps_lat_ref = tags.get("GPS GPSLatitudeRef")
        gps_lon = tags.get("GPS GPSLongitude")
        gps_lon_ref = tags.get("GPS GPSLongitudeRef")

        if gps_lat and gps_lon:
            lat = _to_decimal(gps_lat, str(gps_lat_ref) if gps_lat_ref else "N")
            lon = _to_decimal(gps_lon, str(gps_lon_ref) if gps_lon_ref else "E")
            if lat is not None and lon is not None:
                result["gps"] = {"latitude": lat, "longitude": lon}

    except ImportError:
        result["_exif_error"] = "exifread not available"
    except Exception as e:
        result["_exif_error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def ocr_image(image_path: str) -> str:
    """OCR text from an image.

    Extracts text using the best available OCR backend. Returns text blocks
    with confidence scores and bounding boxes.

    Args:
        image_path: Absolute path to the image file (must be under home directory)
    """
    resolved, err = _validate_path(image_path)
    if err:
        return json.dumps({"error": err}, indent=2)

    # Try OCR
    engine = get_ocr_engine()
    if engine is None:
        return json.dumps(
            {
                "error": (
                    "No OCR backend installed. "
                    "Run: pip install image-analysis-mcp[ocr]"
                ),
                "path": resolved,
            },
            indent=2,
        )

    try:
        blocks = engine(resolved)
    except Exception as e:
        return json.dumps({"error": f"OCR failed: {e}", "path": resolved}, indent=2)

    # Get basic image info for the response
    try:
        from PIL import Image as PilImage
        with PilImage.open(resolved) as img:
            fmt = img.format
            w = img.width
            h = img.height
    except Exception:
        fmt = None
        w = None
        h = None

    full_text = "\n".join(b["text"] for b in blocks) if blocks else ""

    result = {
        "path": resolved,
        "format": fmt,
        "width": w,
        "height": h,
        "text_blocks": blocks or [],
        "full_text": full_text,
    }

    return json.dumps(result, indent=2)


@mcp.tool()
def image_metadata(path: str) -> str:
    """Extract full metadata from an image.

    Returns file info (size, timestamps, SHA-256), image properties
    (format, dimensions, DPI, colour space), and EXIF data including
    camera make/model, datetime, and GPS coordinates.

    Args:
        path: Absolute path to the image file (must be under home directory)
    """
    resolved, err = _validate_path(path)
    if err:
        return json.dumps({"error": err}, indent=2)

    meta = _get_image_metadata(resolved)
    meta["path"] = resolved

    return json.dumps(meta, indent=2)


@mcp.tool()
def extract_text(image_path: str) -> str:
    """Extract all text and metadata from an image.

    Convenience wrapper that combines OCR text extraction with full image
    metadata in a single JSON response.

    Args:
        image_path: Absolute path to the image file (must be under home directory)
    """
    resolved, err = _validate_path(image_path)
    if err:
        return json.dumps({"error": err}, indent=2)

    # Get metadata
    meta = _get_image_metadata(resolved)

    # Try OCR
    engine = get_ocr_engine()
    blocks = None
    if engine is not None:
        try:
            blocks = engine(resolved)
        except Exception:
            pass

    full_text = "\n".join(b["text"] for b in blocks) if blocks else ""

    result = {
        "path": resolved,
        "metadata": meta,
        "text_blocks": blocks or [],
        "full_text": full_text,
    }

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
