# src/graph1/state/global_state.py
from typing import Annotated, List, Optional
from typing_extensions import TypedDict


# ─────────────────────────────────────────────
# PAGE LEVEL SCHEMAS
# ─────────────────────────────────────────────

class WordData(TypedDict):
    text:  str
    bbox:  List[int]          # [x0, y0, x1, y1] normalized
    style: "BlockStyle"


class YoloBlock(TypedDict):
    bbox:       List[int]     # [x0, y0, x1, y1]
    confidence: float


class LabeledBlock(TypedDict):
    bbox:    List[int]        # [x0, y0, x1, y1]
    label:   str              # HEADING, TEXT_BLOCK, TABLE, PAGE_INFO
    words:   List[str]        # words inside this block
    content: str              # joined text content
    styles:  List["BlockStyle"]



class DrawingData(TypedDict):
    bbox:         List[float]     # drawing coordinates may include fractional PDF values
    color:        Optional[tuple] # stroke color
    fill:         Optional[tuple] # fill color
    stroke_width: float           # line thickness
    type:         str             # s=stroke, f=fill


class PageData(TypedDict):
    page_no:         int
    width:           float
    height:          float
    page_image_path: str
    word_data:       List[WordData]
    drawings:        List[DrawingData]  # added
    word_labels:     List[str]
    yolo_blocks:     List[YoloBlock]
    labeled_blocks:  List[LabeledBlock]


# ─────────────────────────────────────────────
# BLUEPRINT SCHEMAS
# ─────────────────────────────────────────────

class BlockStyle(TypedDict):
    font_size: float
    font_name: str
    bold:      bool
    italic:    bool
    color:     Optional[tuple[int, int, int]]
    align:     str


class BlueprintBlock(TypedDict):
    block_id: str
    label:    str
    sub_label: str
    content:  str
    bbox:     List[float]
    style:    BlockStyle


class BlueprintPage(TypedDict):
    page_no:  int
    width:    float
    height:   float
    drawings: List[DrawingData]
    blocks:   List[BlueprintBlock]


class Blueprint(TypedDict):
    total_pages: int
    pages:       List[BlueprintPage]


def merge_pages(
    current: List[PageData],
    updates: List[PageData],
) -> List[PageData]:
    """
    Merge page-level updates from parallel branches by page number.

    Each node can return a partial or full PageData object for a page.
    Updated keys override existing keys for the same page.
    """
    if not current:
        return updates or []
    if not updates:
        return current

    merged_by_page_no = {page["page_no"]: dict(page) for page in current}
    page_order = [page["page_no"] for page in current]

    for page in updates:
        page_no = page["page_no"]
        if page_no in merged_by_page_no:
            merged_by_page_no[page_no] = {
                **merged_by_page_no[page_no],
                **page,
            }
        else:
            merged_by_page_no[page_no] = dict(page)
            page_order.append(page_no)

    return [merged_by_page_no[page_no] for page_no in page_order]


# ─────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────

class GlobalState(TypedDict):
    # --- Input / Metadata ---
    pdf_file: str                # This is the Supabase Storage Path (e.g., "folder/file.pdf")
    user_id: Optional[str]
    request_id: Optional[str]
    user_email: Optional[str]    # Useful for tracking in Graph 1

    # --- THE CLOUD OPTIMIZER ---
    # We store the raw file here so nodes don't re-download from Supabase
    pdf_bytes: Optional[bytes]   

    # --- Processing Data ---
    total_pages: int
    
    # Annotated with your merge_pages function to handle parallel node updates
    pages: Annotated[List[PageData], merge_pages]

    # --- Output ---
    blueprint: Blueprint
    
    # Optional: Track errors across the graph
    errors: List[str]

