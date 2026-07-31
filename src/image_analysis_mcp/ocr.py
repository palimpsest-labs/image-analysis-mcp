"""OCR backend registry with pluggable backends and graceful degradation.

Backends are tried in priority order: rapidocr → tesseract → none.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Each entry: (name, import_name, loader_fn, priority)
# Lower priority number = tried first
_OCR_BACKENDS = []


def register_backend(
    name: str,
    import_name: str,
    loader_fn: callable,
    priority: int = 10,
) -> None:
    """Register an OCR backend.

    Args:
        name: Human-readable backend name (e.g. "rapidocr")
        import_name: Python import path for conditional import
        loader_fn: Callable that returns an OCR engine instance or None
        priority: Lower values are tried first (default 10)
    """
    _OCR_BACKENDS.append((name, import_name, loader_fn, priority))
    _OCR_BACKENDS.sort(key=lambda x: x[3])


# ---------------------------------------------------------------------------
# Built-in backends
# ---------------------------------------------------------------------------


def _load_rapidocr():
    """Try to load RapidOCR onnxruntime backend."""
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()

        def _run_rapidocr(image_path: str) -> Optional[list[dict]]:
            """Run RapidOCR and return structured results."""
            try:
                result, elapse = engine(image_path)
            except Exception:
                return None
            if result is None:
                return None
            blocks = []
            for box, text, confidence in result:
                if not text or not text.strip():
                    continue
                # box is list of [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                x_coords = [p[0] for p in box]
                y_coords = [p[1] for p in box]
                blocks.append({
                    "text": text.strip(),
                    "confidence": round(float(confidence), 4) if confidence else 0.0,
                    "bbox": [min(x_coords), min(y_coords), max(x_coords), max(y_coords)],
                })
            return blocks if blocks else None

        return _run_rapidocr
    except ImportError:
        return None


def _load_tesseract():
    """Try to load pytesseract backend."""
    try:
        import pytesseract
        from PIL import Image

        # Verify tesseract is actually on PATH
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            return None

        def _run_tesseract(image_path: str) -> Optional[list[dict]]:
            """Run Tesseract and return structured results."""
            try:
                img = Image.open(image_path)
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            except Exception:
                return None

            blocks = []
            for i in range(len(data.get("text", []))):
                text = data["text"][i]
                if not text or not text.strip():
                    continue
                conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 0.0
                x = int(data["left"][i])
                y = int(data["top"][i])
                w = int(data["width"][i])
                h = int(data["height"][i])
                blocks.append({
                    "text": text.strip(),
                    "confidence": round(conf / 100.0, 4) if conf > 0 else 0.0,
                    "bbox": [x, y, x + w, y + h],
                })
            return blocks if blocks else None

        return _run_tesseract
    except ImportError:
        return None


# Register built-in backends
register_backend("rapidocr", "rapidocr_onnxruntime", _load_rapidocr, priority=1)
register_backend("tesseract", "pytesseract", _load_tesseract, priority=2)


# ---------------------------------------------------------------------------
# Engine resolution
# ---------------------------------------------------------------------------


def get_ocr_engine(preferred: str = "auto") -> Optional[callable]:
    """Get an OCR engine callable.

    Tries backends in priority order. If *preferred* is set (e.g.
    ``"rapidocr"``), only that backend is attempted.

    Returns a callable ``fn(image_path: str) -> list[dict] | None``
    or ``None`` if no backend is available.
    """
    if preferred != "auto":
        for name, import_name, loader_fn, _priority in _OCR_BACKENDS:
            if name == preferred:
                engine = loader_fn()
                if engine is not None:
                    logger.info("OCR backend: %s", name)
                    return engine
                logger.warning("Preferred OCR backend '%s' not available", name)
                return None

    for name, import_name, loader_fn, _priority in _OCR_BACKENDS:
        engine = loader_fn()
        if engine is not None:
            logger.info("OCR backend: %s", name)
            return engine

    return None
