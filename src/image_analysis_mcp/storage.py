"""Archive storage — JSONL writer with hourly dedup for image analysis results.

Saves every OCR and metadata extraction as timestamped JSONL entries in
~/.local/share/image-analysis/YYYY-MM-DD-image-analysis.jsonl.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


ARCHIVE_DIR = Path.home() / ".local" / "share" / "image-analysis"


def _build_content(tool_name: str, result: dict) -> str:
    """Build a human-readable text blob for full-text search indexing."""
    parts = [tool_name]

    if tool_name == "ocr_image":
        path = result.get("path", "")
        text = result.get("full_text", "")
        if path:
            parts.append(path)
        if text:
            parts.append(text[:500])
    elif tool_name == "image_metadata":
        path = result.get("path", "")
        if path:
            parts.append(path)
        fmt = result.get("format", "")
        if fmt:
            parts.append(f"format={fmt}")
        dims = f"{result.get('width','?')}x{result.get('height','?')}"
        parts.append(f"dimensions={dims}")
        gps = result.get("gps", {})
        if gps:
            parts.append(f"GPS={gps.get('latitude')},{gps.get('longitude')}")
    elif tool_name == "extract_text":
        path = result.get("path", "")
        text = result.get("full_text", "")
        if path:
            parts.append(path)
        meta = result.get("metadata", {})
        fmt = meta.get("format", "")
        if fmt:
            parts.append(f"format={fmt}")
        dims = f"{meta.get('width','?')}x{meta.get('height','?')}"
        parts.append(f"dimensions={dims}")
        if text:
            parts.append(text[:500])
        gps = meta.get("gps", {})
        if gps:
            parts.append(f"GPS={gps.get('latitude')},{gps.get('longitude')}")

    return "; ".join(parts)


def save_analysis(
    tool_name: str,
    result_json: str,
    base_dir: Path | None = None,
) -> str:
    """Save an image analysis result to JSONL archive. Returns the filepath string."""
    base = base_dir or ARCHIVE_DIR
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)

    ts = datetime.now(timezone.utc)
    date_str = ts.strftime("%Y-%m-%d")
    filepath = base / f"{date_str}-image-analysis.jsonl"

    try:
        result_obj = json.loads(result_json) if isinstance(result_json, str) else result_json
    except json.JSONDecodeError:
        result_obj = {"raw": result_json}

    content = _build_content(tool_name, result_obj)

    entry = {
        "tool": tool_name,
        "timestamp": ts.isoformat(),
        "result": result_obj,
        "content": content,
    }

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    os.chmod(filepath, 0o600)
    return str(filepath)
