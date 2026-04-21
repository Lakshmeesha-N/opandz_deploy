import json
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing_extensions import Annotated
from src.graph2.state.schemas import WriterState
from src.utils.llm import get_llm

# Labels that should be rewritten by LLM
REWRITABLE_LABELS = {"HEADING", "TEXT_BLOCK", "TABLE"}

# Sub labels that should never be touched
SKIP_SUB_LABELS = {
    "PAGE_INFO",
    "HEADER_LEFT", "HEADER_RIGHT", "HEADER_CENTER",
    "FOOTER_LEFT", "FOOTER_RIGHT", "FOOTER_CENTER",
}

MAX_TOKENS = 5000
CHARS_PER_TOKEN = 4

def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN

def _build_prompt(blocks_to_rewrite: list[dict], instruction: str) -> str:
    blocks_blueprint = []
    for b in blocks_to_rewrite:
        content = b.get("content", "")
        word_count = len(content.split())
        
        blocks_blueprint.append(
            f"- BLOCK ID: {b['block_id']}\n"
            f"  Type: {b['label']}\n"
            f"  Target Length: EXACTLY {word_count} words\n"
            f"  Original Content: \"{content}\""
        )

    blueprint_text = "\n".join(blocks_blueprint)

    return (
        f"### ROLE\n"
        f"You are an expert document rewriter. Rewrite this document to be about: **{instruction}**.\n\n"
        f"### BLUEPRINT\n"
        f"Below is the document structure. Each block has an ID, type, target length and original content.\n"
        f"{blueprint_text}\n\n"
        f"### RULES\n"
        f"1. **Structural headings** (e.g., 'Introduction', 'Summary') return EXACTLY as they are.\n"
        f"2. **Topic specific headings** must be rewritten to match {instruction}.\n"
        f"3. **Text blocks** must be fully rewritten about {instruction}. Match Target Length EXACTLY.\n"
        f"4. Never mention the original subject.\n"
        f"5. Return ONLY valid JSON: {{\"block_id\": \"rewritten content...\"}}"
    )

def _parse_llm_response(response_text: str) -> dict:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Handle cases like ```json ... ```
        if lines[0].strip().startswith("```"):
            cleaned = "\n".join(lines[1:-1])
    return json.loads(cleaned)

@tool
def rewrite_all(
    instruction: str,
    state: Annotated[WriterState, InjectedState] = None,
) -> str:
    """
    Rewrite the entire document content based on an instruction.
    Updates the filled_placeholders in the state.
    """
    if not state or "filled_placeholders" not in state:
        return "✗ State or filled_placeholders missing."

    placeholders = state["filled_placeholders"]
    llm = get_llm()

    # 1. Collect all rewritable blocks into a list for processing
    all_rewritable = []
    for block_id, data in placeholders.items():
        if (
            data.get("label") in REWRITABLE_LABELS and
            data.get("sub_label") not in SKIP_SUB_LABELS
        ):
            # Create a helper dict that includes the ID
            all_rewritable.append({
                "block_id": block_id,
                **data
            })

    if not all_rewritable:
        return "✗ No rewritable blocks found in document."

    # 2. Token Estimation & Batching
    all_content_text = " ".join([b.get("content", "") for b in all_rewritable])
    estimated_tokens = _estimate_tokens(all_content_text)

    # Prepare batches if text is too large
    batches = []
    if estimated_tokens <= MAX_TOKENS:
        batches.append(all_rewritable)
    else:
        # Fallback: Simple chunking if total size is too big
        # Chunk by 10 blocks at a time to stay safe
        chunk_size = 10
        batches = [all_rewritable[i:i + chunk_size] for i in range(0, len(all_rewritable), chunk_size)]

    total_rewritten = 0
    total_failed = 0

    # 3. Process Batches
    for i, batch in enumerate(batches):
        label = "all" if len(batches) == 1 else f"batch {i+1}"
        prompt = _build_prompt(batch, instruction)
        
        try:
            response = llm.invoke(prompt)
            new_contents = _parse_llm_response(response.content)
            
            for b in batch:
                b_id = b["block_id"]
                if b_id in new_contents:
                    rewritten_text = new_contents[b_id].strip()
                    if rewritten_text:
                        # Update the original state dictionary directly
                        placeholders[b_id]["content"] = rewritten_text
                        total_rewritten += 1
                    else:
                        total_failed += 1
                else:
                    total_failed += 1
                    
            print(f"✓ rewrite_all: {label} processed.")

        except Exception as e:
            print(f"⚠ rewrite_all: {label} failed: {e}")
            total_failed += len(batch)

    return (
        f"✓ Rewrite complete. "
        f"{total_rewritten} blocks rewritten, "
        f"{total_failed} failed."
        if total_rewritten > 0
        else f"✗ No blocks were rewritten. {total_failed} blocks failed."
    )