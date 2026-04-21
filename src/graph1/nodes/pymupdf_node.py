# src/graph1/nodes/pymupdf_node.py
import fitz
from src.graph1.state.schemas import GlobalState, WordData, DrawingData, BlockStyle


def _normalize_bbox(x0: float, y0: float, x1: float, y1: float,
                    page_w: float, page_h: float) -> list[int]:
    """Normalize word bbox to [0, 1000] scale for LiLT input."""
    nx0 = int((x0 / page_w) * 1000)
    ny0 = int((y0 / page_h) * 1000)
    nx1 = int((x1 / page_w) * 1000)
    ny1 = int((y1 / page_h) * 1000)
    return [
        max(0, min(1000, nx0)),
        max(0, min(1000, ny0)),
        max(0, min(1000, nx1)),
        max(0, min(1000, ny1)),
    ]


def _span_style(span: dict) -> BlockStyle:
    flags = span.get("flags", 0)
    bold = bool(flags & 2 ** 4)
    italic = bool(flags & 2 ** 1)
    color_int = int(span.get("color", 0) or 0)
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return BlockStyle(
        font_size=float(span.get("size", 12.0) or 12.0),
        font_name=span.get("font", "") or "",
        bold=bold,
        italic=italic,
        color=(r, g, b),
        align="left",
    )


def _collect_spans(page: fitz.Page) -> list[dict]:
    spans: list[dict] = []
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                bbox = span.get("bbox")
                if not text or not bbox or len(bbox) < 4:
                    continue
                spans.append({
                    "bbox": bbox,
                    "style": _span_style(span),
                })
    return spans


def _find_span_style(word_bbox: tuple[float, float, float, float], spans: list[dict]) -> BlockStyle:
    wx0, wy0, wx1, wy1 = word_bbox
    wcx = (wx0 + wx1) / 2
    wcy = (wy0 + wy1) / 2

    for span in spans:
        sx0, sy0, sx1, sy1 = span["bbox"]
        if sx0 <= wcx <= sx1 and sy0 <= wcy <= sy1:
            return span["style"]

    best_style = None
    best_overlap = -1.0
    for span in spans:
        sx0, sy0, sx1, sy1 = span["bbox"]
        overlap_w = max(0.0, min(wx1, sx1) - max(wx0, sx0))
        overlap_h = max(0.0, min(wy1, sy1) - max(wy0, sy0))
        overlap_area = overlap_w * overlap_h
        if overlap_area > best_overlap:
            best_overlap = overlap_area
            best_style = span["style"]

    return best_style or BlockStyle(
        font_size=12.0,
        font_name="",
        bold=False,
        italic=False,
        color=(0, 0, 0),
        align="left",
    )


def pymupdf_node(state: GlobalState) -> GlobalState:
    """
    Extracts words and drawings from every page using pdf_bytes from state.
    Works entirely in memory—perfect for cloud deployment.
    """
    # 1. Pull bytes from state (No local path, no re-downloading!)
    pdf_bytes = state.get("pdf_bytes")
    pages = state["pages"]

    if not pdf_bytes:
        raise ValueError("Critical Error: 'pdf_bytes' not found in state. Ensure pdf_input_node runs first.")

    # 2. Open PDF from memory stream
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    updated_pages = []

    for page_data in pages:
        pno    = page_data["page_no"] - 1
        page   = doc[pno]
        page_w = page_data["width"]
        page_h = page_data["height"]
        spans  = _collect_spans(page)

        # ── Extract words (normalized for LiLT) ──
        raw_words = page.get_text("words")
        word_data: list[WordData] = []

        for w in raw_words:
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            if not text.strip():
                continue

            style = _find_span_style((x0, y0, x1, y1), spans)

            word_data.append(WordData(
                text=text.strip(),
                bbox=_normalize_bbox(x0, y0, x1, y1, page_w, page_h),
                style=style,
            ))

        # Sort top to bottom, left to right
        word_data.sort(key=lambda w: (w["bbox"][1], w["bbox"][0]))

        # ── Extract drawings ──
        raw_drawings = page.get_drawings()
        drawings: list[DrawingData] = []

        for d in raw_drawings:
            rect = d.get("rect")
            if not rect:
                continue

            drawings.append(DrawingData(
                bbox         = list(rect),
                color        = d.get("color"),
                fill         = d.get("fill"),
                stroke_width = float(d.get("width") or 0.0),
                type         = d.get("type", "s"),
            ))

        print(f"✓ pymupdf_node: page {page_data['page_no']} → {len(word_data)} words")

        # 3. CRITICAL: Merge instead of overwrite
        # We must keep page_image_path and metadata from pdf_input_node
        new_page_data = dict(page_data) # Start with existing data
        new_page_data.update({
            "word_data": word_data,
            "drawings":  drawings,
        })
        updated_pages.append(new_page_data)

    doc.close()

    # return the updated list of pages to the GlobalState
    return {"pages": updated_pages}