# src/graph1/nodes/yolo_node.py
import fitz
import PIL.Image
import io
from ultralytics import YOLO
from src.graph1.state.schemas import GlobalState, YoloBlock
from src.core.config import settings

# Load model once at module level
_yolo_model = None

def _get_yolo_model() -> YOLO:
    global _yolo_model
    if _yolo_model is None:
        _yolo_model = YOLO(settings.yolo_model_path)
    return _yolo_model


def _pixel_to_normalized_coords(
    px0: float, py0: float, px1: float, py1: float,
    img_w: int,  img_h: int,
) -> list[int]:
    """
    Convert YOLO pixel bbox → normalized [0, 1000] scale.
    Matches word bbox scale so merge_node can compare directly.
    """
    nx0 = int((px0 / img_w) * 1000)
    ny0 = int((py0 / img_h) * 1000)
    nx1 = int((px1 / img_w) * 1000)
    ny1 = int((py1 / img_h) * 1000)
    return [
        max(0, min(1000, nx0)),
        max(0, min(1000, ny0)),
        max(0, min(1000, nx1)),
        max(0, min(1000, ny1)),
    ]


def _is_inside(small: list, large: list) -> bool:
    """
    Check if small block is fully contained inside large block.
    Both bboxes in [0, 1000] normalized scale.
    """
    return (
        small[0] >= large[0] and  # x0
        small[1] >= large[1] and  # y0
        small[2] <= large[2] and  # x1
        small[3] <= large[3]      # y1
    )


def _remove_contained_blocks(blocks: list[YoloBlock]) -> list[YoloBlock]:
    """
    Remove small blocks that are fully contained inside larger blocks.
    Keep large blocks, discard small contained ones.
    For document mimicry we want large blocks so LLM fills
    entire section as one unit.
    """
    if len(blocks) <= 1:
        return blocks

    to_remove = set()

    for i, block_a in enumerate(blocks):
        for j, block_b in enumerate(blocks):
            if i == j:
                continue
            # If block_a is fully inside block_b → discard block_a
            if _is_inside(block_a["bbox"], block_b["bbox"]):
                to_remove.add(i)

    return [b for i, b in enumerate(blocks) if i not in to_remove]


def yolo_node(state: GlobalState) -> GlobalState:
    """
    Runs YOLO block detection on each page image.

    Responsibilities:
    - Loads YOLO model once
    - For each page runs YOLO on page PNG
    - Filters detections by confidence threshold
    - Applies IOU suppression for partial overlaps
    - Removes small blocks contained inside large blocks
    - Converts pixel bboxes to [0, 1000] normalized scale
    - Stores clean results in yolo_blocks for each page
    """

    pages     = state["pages"]
    model     = _get_yolo_model()
    threshold = settings.yolo_confidence_threshold
    iou       = settings.yolo_iou_threshold

    updated_pages = []

    for page_data in pages:
        page_image_path = page_data["page_image_path"]

        # ── Run YOLO ──────────────────────────
        results = model.predict(
            source  = page_image_path,
            conf    = threshold,
            iou     = iou,
            verbose = False,
        )

        yolo_blocks: list[YoloBlock] = []

        if results and len(results) > 0:
            result = results[0]
            img_w  = result.orig_shape[1]   # image width in pixels
            img_h  = result.orig_shape[0]   # image height in pixels
            boxes  = result.boxes

            for box in boxes:
                confidence = float(box.conf[0])

                if confidence < threshold:
                    continue

                # YOLO bbox in pixel coords (xyxy format)
                px0, py0, px1, py1 = box.xyxy[0].tolist()

                # Convert to [0, 1000] normalized scale
                norm_bbox = _pixel_to_normalized_coords(
                    px0, py0, px1, py1,
                    img_w, img_h,
                )

                yolo_blocks.append(YoloBlock(
                    bbox       = norm_bbox,
                    confidence = confidence,
                ))

        # ── Remove contained small blocks ─────
        clean_blocks = _remove_contained_blocks(yolo_blocks)

        print(
            f"✓ yolo_node: page {page_data['page_no']} → "
            f"{len(yolo_blocks)} detected → "
            f"{len(clean_blocks)} after containment filter"
        )

        updated_pages.append({
            "page_no":     page_data["page_no"],
            "yolo_blocks": clean_blocks,
        })

    return {"pages": updated_pages}
