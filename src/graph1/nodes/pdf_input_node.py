import fitz  # PyMuPDF
import os
from src.graph1.state.schemas import GlobalState, PageData
from src.core.config import settings
from src.core.exceptions import PdfTooManyPagesError
from src.core.dependencies import supabase

def pdf_input_node(state: GlobalState) -> GlobalState:
    """
    Downloads PDF from Supabase, saves it to a request-specific local temp folder,
    and initializes the graph state.
    """
    request_id = state["request_id"]
    storage_path = state["pdf_file"] 

    # --- 1. SET UP TEMP DIRECTORY ---
    # Creates: temp/05acf5e4.../
    temp_dir = os.path.join("temp", request_id)
    os.makedirs(temp_dir, exist_ok=True)
    local_pdf_path = os.path.join(temp_dir, "original.pdf")

    # --- 2. DOWNLOAD FROM SUPABASE STORAGE ---
    try:
        pdf_bytes = supabase.storage.from_("opandz-assets").download(storage_path)
        
        # Write bytes to the local temp file
        with open(local_pdf_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"✅ PDF downloaded and saved locally: {local_pdf_path}")
        
    except Exception as e:
        error_msg = f"Storage Download/Write Error: {str(e)}"
        print(f"❌ {error_msg}")
        supabase.table("requests").update({
            "status": "failed",
            "error_log": error_msg
        }).eq("request_id", request_id).execute()
        raise e

    # --- 3. OPEN PDF FROM LOCAL PATH ---
    try:
        # Now we open the actual file from the disk
        doc = fitz.open(local_pdf_path)
        total_pages = len(doc)
    except Exception as e:
        print(f"❌ Failed to open PDF from local path {local_pdf_path}: {e}")
        raise e

    # --- 4. VALIDATE PAGE LIMIT ---
    if total_pages > settings.max_pages:
        doc.close()
        supabase.table("requests").update({
            "status": "failed",
            "error_log": f"PDF too long: {total_pages} pages (Max: {settings.max_pages})"
        }).eq("request_id", request_id).execute()
        raise PdfTooManyPagesError(f"PDF exceeds limit of {settings.max_pages} pages.")


    # --- 6. INITIALIZE PAGE DATA OBJECTS ---
    pages: list[PageData] = []
    for pno in range(total_pages):
        page = doc[pno]
        
        # Crucial: Set page_image_path to a local temp file path for YOLO
        local_image_path = os.path.join(temp_dir, f"page_{pno + 1}.png")

        pages.append(PageData(
            page_no         = pno + 1,
            width           = float(page.rect.width),
            height          = float(page.rect.height),
            page_image_path = local_image_path, # Other nodes will look here
            word_data       = [],
            drawings        = [],
            word_labels     = [],
            yolo_blocks     = [],
            labeled_blocks  = [],
        ))

    doc.close()
    print(f"✅ Input Node Complete: Local files initialized in {temp_dir}")

    # --- 7. RETURN STATE ---
    return {
        "pdf_bytes":   pdf_bytes,      # Keep in RAM for OCR speed
        "pdf_file":    local_pdf_path, # Downstream nodes now have the LOCAL path
        "total_pages": total_pages,
        "pages":       pages,
        "blueprint":   {},
        "errors":      [],
    }