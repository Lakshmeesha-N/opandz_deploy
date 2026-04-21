import json
from collections import Counter
from typing import Optional

# Core imports
from src.core.dependencies import supabase
from src.graph1.state.schemas import GlobalState, Blueprint, BlueprintPage, BlueprintBlock, BlockStyle

# ─────────────────────────────────────────────
# HELPERS (Layout & Styling)
# ─────────────────────────────────────────────

def pt_to_px(pt: Optional[float]) -> float:
    """Convert PDF points to CSS pixels."""
    if pt is None:
        return 0.0
    return float(pt) * 1.333

def _denormalize_bbox(bbox: list[int], page_w: float, page_h: float) -> list[float]:
    """Convert normalized [0, 1000] bbox → actual PDF coordinates (points)."""
    x0, y0, x1, y1 = bbox
    return [
        round((x0 / 1000) * page_w, 2),
        round((y0 / 1000) * page_h, 2),
        round((x1 / 1000) * page_w, 2),
        round((y1 / 1000) * page_h, 2),
    ]

def _normalize_color(color) -> Optional[tuple]:
    """Normalize PyMuPDF float color (0-1) to RGB int (0-255)."""
    if not color:
        return None
    if isinstance(color, (list, tuple)):
        if len(color) >= 3 and isinstance(color[0], float):
            return tuple(int(c * 255) for c in color[:3])
        return tuple(int(c) for c in color[:3])
    return None

def _rgb_to_css(color) -> str:
    if not color:
        return "transparent"
    return f"rgb({color[0]}, {color[1]}, {color[2]})"

def _dominant_style(styles: list[dict]) -> dict:
    """Take the most common style values from a block's word styles."""
    if not styles:
        return {
            "font_size": 12.0, "font_name": "", "bold": False,
            "italic": False, "color": (0, 0, 0), "align": "left",
        }

    font_sizes = [style["font_size"] for style in styles]
    font_names = [style["font_name"] for style in styles]
    colors = [style["color"] for style in styles if style.get("color")]
    aligns = [style["align"] for style in styles if style.get("align")]

    dominant_size = Counter(font_sizes).most_common(1)[0][0]
    dominant_name = Counter(font_names).most_common(1)[0][0]
    dominant_color = Counter(colors).most_common(1)[0][0] if colors else (0, 0, 0)
    dominant_align = Counter(aligns).most_common(1)[0][0] if aligns else "left"

    return {
        "font_size": float(dominant_size),
        "font_name": dominant_name,
        "bold": sum(1 for style in styles if style["bold"]) > len(styles) / 2,
        "italic": sum(1 for style in styles if style["italic"]) > len(styles) / 2,
        "color": dominant_color,
        "align": dominant_align,
    }

def _compute_sub_label(label: str, bbox: list[float], page_w: float, page_h: float) -> str:
    """Classify PAGE_INFO blocks by page half and horizontal center."""
    if not bbox or len(bbox) < 4 or page_w <= 0 or page_h <= 0:
        return label
    if label != "PAGE_INFO":
        return label

    x0, y0, x1, y1 = bbox
    x_center = ((x0 + x1) / 2) / page_w
    y_center = ((y0 + y1) / 2) / page_h

    horizontal = "LEFT" if x_center < 0.33 else "RIGHT" if x_center > 0.66 else "CENTER"
    return f"HEADER_{horizontal}" if y_center <= 0.5 else f"FOOTER_{horizontal}"

# ─────────────────────────────────────────────
# GINJA TEMPLATE GENERATOR
# ─────────────────────────────────────────────

def _generate_ginja_page(page_no: int, page_w: float, page_h: float, labeled_blocks: list, drawings: list) -> str:
    page_width_px = pt_to_px(page_w)
    page_height_px = pt_to_px(page_h)

    html = [f'<div style="position:relative; width:{page_width_px}px; height:{page_height_px}px; overflow:hidden;">']

    # Drawings (Background)
    for drawing in drawings:
        raw_bbox = drawing.get("bbox", [])
        if not raw_bbox or len(raw_bbox) < 4: continue
        x0, y0, x1, y1 = raw_bbox
        
        style = (
            f"position:absolute; left:{pt_to_px(x0)}px; top:{pt_to_px(y0)}px; "
            f"width:{pt_to_px(x1-x0)}px; height:{pt_to_px(y1-y0)}px;"
        )
        fill = _normalize_color(drawing.get("fill"))
        if fill: style += f"background:{_rgb_to_css(fill)};"
        
        stroke = _normalize_color(drawing.get("color"))
        if stroke: style += f"border:{drawing.get('stroke_width', 1.0)}px solid {_rgb_to_css(stroke)};"
        
        html.append(f'<div style="{style}"></div>')

    # Text blocks (Foreground)
    for block_no, block in enumerate(labeled_blocks, start=1):
        block_id = f"{page_no}_{block_no}"
        x0, y0, x1, y1 = block["pdf_bbox"]
        
        buffer = 8 if block["label"] == "HEADING" else 0
        b_style = block["style"]
        
        style = (
            f"position:absolute; left:{pt_to_px(x0)-buffer}px; top:{pt_to_px(y0)-buffer}px; "
            f"width:{pt_to_px(x1-x0)+(buffer*2)}px; height:{pt_to_px(y1-y0)+(buffer*2)}px; "
            f"font-size:{pt_to_px(b_style['font_size'])}px; font-family:{b_style['font_name'] or 'serif'}, serif; "
            f"font-weight:{'bold' if b_style['bold'] else 'normal'}; font-style:{'italic' if b_style['italic'] else 'normal'}; "
            f"color:{_rgb_to_css(b_style['color'])}; text-align:{b_style.get('align', 'left')}; "
            f"line-height:1.2; padding:1px; white-space:pre-wrap; overflow:hidden;"
        )
        html.append(f'<div style="{style}">{{{{ {block_id} }}}}</div>')

    html.append("</div>")
    return "\n".join(html)

# ─────────────────────────────────────────────
# PRODUCTION BLUEPRINT NODE
# ─────────────────────────────────────────────

def blueprint_node(state: GlobalState) -> dict:
    pages = state["pages"]
    request_id = state["request_id"]
    blueprint_pages = []
    
    # Mapping block_id -> {label, sub_label, content}
    # This will be stored in the 'placeholders' column in Supabase
    placeholders_data = {}

    for page_data in pages:
        labeled_blocks = page_data["labeled_blocks"]
        drawings = page_data.get("drawings", [])
        page_no, page_w, page_h = page_data["page_no"], page_data["width"], page_data["height"]

        blueprint_blocks = []
        enriched_blocks = []

        for block_no, block in enumerate(labeled_blocks, start=1):
            block_id = f"{page_no}_{block_no}"
            pdf_bbox = _denormalize_bbox(block["bbox"], page_w, page_h)
            dominant = _dominant_style(block.get("styles", []))
            sub_label = _compute_sub_label(block["label"], pdf_bbox, page_w, page_h)

            # 1. Store ONLY the metadata and text in placeholders
            placeholders_data[block_id] = {
                "label": block["label"],
                "sub_label": sub_label,
                "content": block["content"]
            }

            # 2. Store ONLY the layout/geometry in the blueprint
            # Content key is completely removed
            blueprint_blocks.append({
                "block_id": block_id,
                "bbox": pdf_bbox,
                "style": dominant
            })
            
            # Needed for the .ginja generation logic inside this loop
            enriched_blocks.append({**block, "pdf_bbox": pdf_bbox, "style": dominant})

        # 3. Generate & Upload .ginja Template
        # This allows the renderer to know where to put the text later
        ginja_html = _generate_ginja_page(page_no, page_w, page_h, enriched_blocks, drawings)
        storage_path = f"{request_id}/templates/{page_no}.ginja"
        
        try:
            supabase.storage.from_("opandz-assets").upload(
                path=storage_path,
                file=ginja_html.encode('utf-8'),
                file_options={"content-type": "text/plain", "upsert": "true"}
            )
        except Exception as e:
            print(f"⚠ Error uploading template for page {page_no}: {e}")

        blueprint_pages.append({
            "page_no": page_no, 
            "width": page_w, 
            "height": page_h,
            "drawings": drawings, 
            "blocks": blueprint_blocks,
        })

    # Final result for the 'blueprints' table
    final_blueprint = {
        "total_pages": state["total_pages"],
        "pages": blueprint_pages,
    }

    try:
        # 4. Save to Supabase Table 'blueprints'
        # blueprint_json = LAYOUT ONLY
        # placeholders = DATA ONLY
        supabase.table("blueprints").insert({
            "request_id": request_id,
            "blueprint_json": final_blueprint,
            "placeholders": placeholders_data 
        }).execute()

        # 5. Mark request as ready in the main tracking table
        supabase.table("requests").update({"status": "ready"}).eq("request_id", request_id).execute()
        print(f"✓ Production: Cloud Assets Ready for ID {request_id}")
        
    except Exception as e:
        print(f"⚠ Error saving blueprint to database: {e}")

    return {"blueprint": final_blueprint}