# src/graph1/nodes/lilt_node.py
import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from src.graph1.state.schemas import GlobalState
from src.core.config import settings


# ── Load model and tokenizer once at module level ──
_model     = None
_tokenizer = None

def _get_model_and_tokenizer():
    global _model, _tokenizer
    if _model is None or _tokenizer is None:
        # settings.lilt_model_path should be relative like "models/lilt-finetuned"
        _tokenizer = AutoTokenizer.from_pretrained(settings.lilt_model_path)
        _model     = AutoModelForTokenClassification.from_pretrained(
            settings.lilt_model_path
        )
        _model.eval()
        # Move to GPU if Railway provides one, otherwise CPU is fine for LiLT
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model.to(device)
        print(f"✓ LiLT model loaded onto {device}")
    return _model, _tokenizer


def _run_lilt_on_words(
    words:     list[str],
    bboxes:    list[list[int]],
    model,
    tokenizer,
) -> list[str]:
    """
    Run LiLT on all words of a page at once.
    Returns one label string per word.
    """

    if not words:
        return []

    # ── Tokenize ──────────────────────────────
    encoding = tokenizer(
        words,
        boxes               = bboxes,
        is_split_into_words = True,   # each item in list is one word
        return_tensors      = "pt",
        truncation          = True,   # safety net for very long pages
        max_length          = 512,
        padding             = True,
    )

    # ── Run LiLT ──────────────────────────────
    with torch.no_grad():
        outputs = model(**encoding)

    # Get predicted class per token
    token_predictions = outputs.logits.argmax(-1).squeeze().tolist()

    # Handle single token edge case
    if isinstance(token_predictions, int):
        token_predictions = [token_predictions]

    # ── Map tokens back to words ──────────────
    word_ids = encoding.word_ids()

    word_label_map = {}
    for token_idx, word_idx in enumerate(word_ids):
        if word_idx is None:
            continue
        # Take first token prediction per word
        if word_idx not in word_label_map:
            word_label_map[word_idx] = model.config.id2label.get(
                token_predictions[token_idx], "B-TEXT_BLOCK"
            )

    # Build final word labels in order
    word_labels = [
        word_label_map.get(i, "B-TEXT_BLOCK")
        for i in range(len(words))
    ]

    return word_labels


def lilt_node(state: GlobalState) -> GlobalState:
    """
    Corrected version for Cloud:
    - Uses Singleton for model loading
    - Preserves all previous page data (Images, YOLO blocks, Word coordinates)
    """
    pages            = state["pages"]
    model, tokenizer = _get_model_and_tokenizer()
    updated_pages    = []

    for page_data in pages:
        # Access word_data safely
        word_data = page_data.get("word_data", [])

        if not word_data:
            print(f"⚠ lilt_node: page {page_data['page_no']} has no words — skipping")
            # Return the original page_data so we don't lose the metadata
            updated_pages.append(page_data)
            continue

        # Extract words and bboxes (already normalized by pymupdf_node)
        words  = [w["text"] for w in word_data]
        bboxes = [w["bbox"] for w in word_data]

        # Run LiLT Inference
        word_labels = _run_lilt_on_words(words, bboxes, model, tokenizer)

        # ── THE FIX: MERGE DATA ──
        # Start with a full copy of the current page data
        new_page_data = dict(page_data) 
        # Only add/update the word_labels
        new_page_data["word_labels"] = word_labels 
        
        updated_pages.append(new_page_data)

    # Return the FULL list of pages back to the graph state
    return {"pages": updated_pages}
