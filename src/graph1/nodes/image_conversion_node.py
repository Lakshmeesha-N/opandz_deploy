import fitz
import os
from src.graph1.state.schemas import GlobalState
from src.core.config import settings

def image_conversion_node(state: GlobalState) -> GlobalState:
    # 1. Get bytes from state (don't reopen from a path that doesn't exist!)
    pdf_bytes = state.get("pdf_bytes")
    pages = state["pages"]
    request_id = state["request_id"]

    if not pdf_bytes:
        raise ValueError("No PDF bytes found in state. Did pdf_input_node run?")

    # 2. Open PDF from memory
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # 3. Ensure the local directory exists
    os.makedirs(request_id, exist_ok=True)

    for page_data in pages:
        pno = page_data["page_no"] - 1
        page = doc[pno]
        page_image_path = page_data["page_image_path"]

        # Render at zoom level (e.g., 2.0x for better YOLO accuracy)
        zoom = settings.image_zoom
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        
        # Save to disk so YOLO can find it
        pix.save(page_image_path)

        print(f"✓ image_conversion_node: page {page_data['page_no']} saved to {page_image_path}")

    doc.close()
    return {} 