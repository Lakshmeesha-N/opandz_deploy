import json
from pathlib import Path
from weasyprint import HTML

def pt_to_px(v):
    return v * 1.333  # convert points to pixels

def normalize_color(color):
    if not color:
        return None
    if max(color) <= 1:  # values in 0–1 range
        return [int(c * 255) for c in color]
    return [int(c) for c in color]

def rgb(color):
    if not color:
        return None
    return f"rgb({color[0]},{color[1]},{color[2]})"

def build_html(blueprint_json, filled_json):
    """Build HTML string from blueprint + filled content."""
    html = []
    html.append("""
    <html>
    <head>
    <style>
        @page { margin: 0; }
        body { margin:0; padding:0; font-family:"Times New Roman", serif; }
        .page { position: relative; page-break-after: always; }
        .block { position: absolute; white-space: pre-wrap; overflow:hidden; }
    </style>
    </head>
    <body>
    """)

    for page in blueprint_json.get("pages", []):
        W = pt_to_px(page.get("width", 612))
        H = pt_to_px(page.get("height", 792))
        html.append(f'<div class="page" style="width:{W}px;height:{H}px;">')

        # 1️⃣ Draw background shapes first
        for d in page.get("drawings", []):
            x0, y0, x1, y1 = d["bbox"]
            left   = pt_to_px(x0)
            top    = pt_to_px(y0)
            width  = max(1, pt_to_px(x1 - x0))
            height = max(1, pt_to_px(y1 - y0))

            fill   = rgb(normalize_color(d.get("fill")))
            stroke = rgb(normalize_color(d.get("color")))
            sw     = d.get("stroke_width", 1)

            style = f"position:absolute;left:{left}px;top:{top}px;width:{width}px;height:{height}px;"
            if fill:
                style += f"background:{fill};"
            if stroke:
                style += f"border:{sw}px solid {stroke};"

            html.append(f'<div style="{style}"></div>')

        # 2️⃣ Draw text blocks
        for block in page.get("blocks", []):
            block_id = block["block_id"]
            content = filled_json.get(block_id, {}).get("content", "")
            if not content:
                continue

            x0, y0, x1, y1 = block["bbox"]
            left   = pt_to_px(x0)
            top    = pt_to_px(y0)
            width  = pt_to_px(x1 - x0)
            height = pt_to_px(y1 - y0)

            s            = block.get("style", {})
            font_size    = pt_to_px(s.get("font_size", 12))
            font_weight  = "bold"   if s.get("bold")   else "normal"
            font_style   = "italic" if s.get("italic") else "normal"
            text_align   = s.get("align", "left")
            color        = rgb(normalize_color(s.get("color", [0, 0, 0])))

            style = (
                f"position:absolute;left:{left}px;top:{top}px;width:{width}px;height:{height}px;"
                f"font-size:{font_size}px;font-family:'Times New Roman', serif;"
                f"font-weight:{font_weight};font-style:{font_style};"
                f"color:{color};text-align:{text_align};line-height:1.2;"
            )
            html.append(f'<div class="block" style="{style}">{content}</div>')

        html.append("</div>")  # end page

    html.append("</body></html>")
    return "".join(html)

def render_to_pdf(blueprint_json: dict, filled_json: dict, output_path: str) -> str:
    """
    Render all pages to one PDF using WeasyPrint.
    Writes the PDF to disk and returns the output path,
    so FastAPI can stream it back to the client.
    """
    html = build_html(blueprint_json, filled_json)
    pdf_bytes = HTML(string=html).write_pdf()
    Path(output_path).write_bytes(pdf_bytes)
    return output_path


