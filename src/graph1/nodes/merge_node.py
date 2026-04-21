# src/graph1/nodes/merge_node.py
from collections import Counter
from src.graph1.state.schemas import GlobalState, LabeledBlock
import os
import shutil  

# Gap thresholds in [0, 1000] normalized scale
ORPHAN_VERTICAL_GAP   = 20    # max vertical gap to be same block
ORPHAN_HORIZONTAL_GAP = 100   # max horizontal gap to be same line


def _point_in_bbox(
    wx0: int, wy0: int, wx1: int, wy1: int,
    bx0: int, by0: int, bx1: int, by1: int,
    tolerance: int = 10,
) -> bool:
    """Check if word center falls inside block bbox with tolerance."""
    wcx = (wx0 + wx1) // 2
    wcy = (wy0 + wy1) // 2
    return (
        wcx >= bx0 - tolerance and
        wcx <= bx1 + tolerance and
        wcy >= by0 - tolerance and
        wcy <= by1 + tolerance
    )


def _majority_vote(labels: list[str]) -> str:
    """Return most common base label from a list of BIO labels."""
    if not labels:
        return "TEXT_BLOCK"

    base_labels = [
        lbl.split("-")[1] if "-" in lbl else lbl
        for lbl in labels
    ]
    return Counter(base_labels).most_common(1)[0][0]


def _build_labeled_block(
    block_words:  list[dict],
    block_labels: list[str],
    bbox:         list,
) -> LabeledBlock:
    """Build a LabeledBlock from words labels and bbox."""
    label   = _majority_vote(block_labels)
    words   = [w["text"] for w in block_words]
    styles  = [w["style"] for w in block_words if "style" in w]
    content = " ".join(words)

    return LabeledBlock(
        bbox    = [int(v) for v in bbox],
        label   = label,
        words   = words,
        content = content,
        styles  = styles,
    )


def _group_orphan_words(
    orphan_words:  list[dict],
    orphan_labels: list[str],
) -> list[LabeledBlock]:
    """
    Group orphan words into blocks using both vertical
    and horizontal gap checks.

    Same block if:
        vertical gap <= ORPHAN_VERTICAL_GAP
        AND horizontal gap <= ORPHAN_HORIZONTAL_GAP

    New block if:
        vertical gap > ORPHAN_VERTICAL_GAP
        OR horizontal gap > ORPHAN_HORIZONTAL_GAP
        (words far apart on same line = separate entities)
    """
    if not orphan_words:
        return []

    # Sort by vertical then horizontal position
    paired = sorted(
        zip(orphan_words, orphan_labels),
        key=lambda x: (x[0]["bbox"][1], x[0]["bbox"][0])
    )

    orphan_blocks: list[LabeledBlock] = []
    current_words  = [paired[0][0]]
    current_labels = [paired[0][1]]
    current_bbox   = list(paired[0][0]["bbox"])

    for word, label in paired[1:]:
        word_bbox = word["bbox"]
        prev_bbox = current_words[-1]["bbox"]

        # Vertical gap: top of current word - bottom of previous word
        vertical_gap = word_bbox[1] - prev_bbox[3]

        # Horizontal gap: left of current word - right of previous word
        horizontal_gap = word_bbox[0] - prev_bbox[2]

        same_block = (
            vertical_gap   <= ORPHAN_VERTICAL_GAP and
            horizontal_gap <= ORPHAN_HORIZONTAL_GAP
        )

        if same_block:
            # Extend current block
            current_words.append(word)
            current_labels.append(label)

            # Expand bbox to cover this word
            current_bbox[0] = min(current_bbox[0], word_bbox[0])  # x0
            current_bbox[1] = min(current_bbox[1], word_bbox[1])  # y0
            current_bbox[2] = max(current_bbox[2], word_bbox[2])  # x1
            current_bbox[3] = max(current_bbox[3], word_bbox[3])  # y1
        else:
            # Save current block and start new one
            orphan_blocks.append(_build_labeled_block(
                current_words, current_labels, current_bbox
            ))
            current_words  = [word]
            current_labels = [label]
            current_bbox   = list(word_bbox)

    # Save last group
    orphan_blocks.append(_build_labeled_block(
        current_words, current_labels, current_bbox
    ))

    return orphan_blocks


def merge_node(state: GlobalState) -> GlobalState:
    """
    Merges YOLO block bboxes with LiLT word labels.

    Responsibilities:
    - For each YOLO block find all words inside its bbox
    - Majority vote on word labels → one label per block
    - Group orphan words into new blocks using vertical
      and horizontal gap checks
    - Combines YOLO blocks and orphan blocks into labeled_blocks
    - Stores results in each PageData
    """

    pages         = state["pages"]
    updated_pages = []

    temp_path = f"/tmp/{request_id}" 

    if os.path.exists(temp_path):
        try:
            # This deletes the entire folder and all files inside
            shutil.rmtree(temp_path)
            print(f"♻️ merge_node: Automatically cleared temp folder for {request_id}")
        except Exception as e:
            print(f"⚠ merge_node: Failed to delete temp folder: {e}")

    for page_data in pages:
        word_data   = page_data["word_data"]
        word_labels = page_data["word_labels"]
        yolo_blocks = page_data["yolo_blocks"]

        if not word_data:
            print(f"⚠ merge_node: page {page_data['page_no']} has no words — skipping")
            updated_pages.append({
                "page_no":        page_data["page_no"],
                "labeled_blocks": [],
            })
            continue

        labeled_blocks:      list[LabeledBlock] = []
        matched_word_indices: set[int]          = set()

        # ── Step 1: Match words to YOLO blocks ──
        for yolo_block in yolo_blocks:
            bx0, by0, bx1, by1 = yolo_block["bbox"]

            block_words:        list[dict] = []
            block_labels:       list[str]  = []
            block_word_indices: list[int]  = []

            for idx, (word, label) in enumerate(zip(word_data, word_labels)):
                wx0, wy0, wx1, wy1 = word["bbox"]

                if _point_in_bbox(wx0, wy0, wx1, wy1, bx0, by0, bx1, by1):
                    block_words.append(word)
                    block_labels.append(label)
                    block_word_indices.append(idx)

            # Skip YOLO block with no words inside
            if not block_words:
                continue

            matched_word_indices.update(block_word_indices)

            labeled_blocks.append(_build_labeled_block(
                block_words, block_labels, yolo_block["bbox"]
            ))

        # ── Step 2: Handle orphan words ──────────
        orphan_words:  list[dict] = []
        orphan_labels: list[str]  = []

        for idx, (word, label) in enumerate(zip(word_data, word_labels)):
            if idx not in matched_word_indices:
                orphan_words.append(word)
                orphan_labels.append(label)

        orphan_blocks = _group_orphan_words(orphan_words, orphan_labels)

        # ── Step 3: Combine and sort ──────────────
        all_blocks = labeled_blocks + orphan_blocks
        all_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

        print(
            f"✓ merge_node: page {page_data['page_no']} → "
            f"{len(labeled_blocks)} YOLO blocks + "
            f"{len(orphan_blocks)} orphan blocks = "
            f"{len(all_blocks)} total blocks"
        )

        updated_pages.append({
            "page_no":        page_data["page_no"],
            "labeled_blocks": all_blocks,
        })

    return {"pages": updated_pages}
