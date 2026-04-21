from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing import Optional
from typing_extensions import Annotated
from src.graph2.state.schemas import WriterState
from src.utils.llm import get_llm


def _find_block(filled_placeholders: dict, block_id: str) -> Optional[dict]:
    """Find and return block dict by block_id (flat dictionary lookup)."""
    return filled_placeholders.get(block_id)


def _build_rewrite_prompt(block: dict, instruction: str) -> str:
    """Build LLM prompt for rewriting a single block."""
    content = block.get("content", "")
    word_count = len(content.split())

    return (
        f"You are rewriting a single block in a document.\n\n"
        f"Block type: {block.get('label', 'TEXT_BLOCK')}\n"
        f"Current content:\n{content}\n\n"
        f"Instruction: {instruction}\n\n"
        f"Rules:\n"
        f"- Strictly follow the length: it should not exceed {word_count} words.\n"
        f"- Return ONLY the rewritten content. No explanation, no preamble.\n"
        f"- Match the tone and length appropriate for a {block.get('label')} block.\n"
        f"- For HEADING blocks: keep it short, no punctuation at end.\n"
        f"- For TEXT_BLOCK: write full sentences, match approximate length of original.\n"
        f"- Do NOT add markdown, bullet points, or formatting symbols.\n"
        f"- For TEXT_BLOCK: if the block is one paragraph, rewrite as a paragraph"
        f"if the block is point-wise, rewrite point-wise.\n"
        f"- Do NOT add markdown, bullet points, or formatting symbols unless the original block is point-wise.\n"
        f"Rewritten content:\n"
    )


def _apply_rewrite_block(
    filled_placeholders: dict,
    block_id: str,
    new_content: str,
) -> tuple[dict, str]:
    """
    Core logic for applying rewritten content to a single block.
    Returns the updated placeholders and a confirmation/error message.
    """
    print(f"Applying rewrite to block '{block_id}' with new content: {new_content[:50]}...")
    block = _find_block(filled_placeholders, block_id)
    if block is None:
        return (
            filled_placeholders,
            f"✗ Block '{block_id}' not found. "
            f"Block IDs are in format page_block e.g. 1_1, 2_3."
        )

    if block.get("label") == "PAGE_INFO" or block.get("sub_label") == "PAGE_INFO":
        return (
            filled_placeholders,
            f"✗ Block '{block_id}' is a protected metadata/page info block. "
            f"Use the change_block tool instead."
        )

    old_content = block.get("content", "")
    if not new_content:
        return (
            filled_placeholders,
            f"✗ Empty rewritten content for block '{block_id}'. Block not modified."
        )

    block["content"] = new_content
    return (
        filled_placeholders,
        f"✓ Block '{block_id}' ({block.get('label')}) rewritten.\n"
        f"Old: {old_content[:100]}{'...' if len(old_content) > 100 else ''}\n"
        f"New: {new_content[:100]}{'...' if len(new_content) > 100 else ''}"
    )


@tool
def rewrite_block(
    block_id: str,
    instruction: str,
    state: Annotated[WriterState, InjectedState] = None,
) -> str:
    """
    Rewrite the content of a specific block using an instruction.
    Use this when the user wants to change a particular block's content.
    Do NOT use this for headers or footers — use change_block instead.
    """
    if not state or "filled_placeholders" not in state:
        return "✗ State or filled_placeholders missing."

    placeholders = state["filled_placeholders"]
    block = _find_block(placeholders, block_id)
    if block is None:
        return (
            f"✗ Block '{block_id}' not found in the current document. "
            f"Please verify the ID (e.g., '1_1', '2_3')."
        )

    if block.get("label") == "PAGE_INFO" or block.get("sub_label") == "PAGE_INFO":
        return (
            f"✗ Block '{block_id}' is a protected metadata/page info block. "
            f"Use the change_block tool for manual edits instead."
        )

    llm = get_llm()
    prompt = _build_rewrite_prompt(block, instruction)
    print(f"Invoking LLM for block '{block_id}' with instruction: {prompt}... ")
    try:
        response = llm.invoke(prompt)
        new_content = response.content.strip()
        print(f"LLM response for block '{block_id}': {new_content}...")
    except Exception as e:
        return f"✗ LLM call failed for block '{block_id}': {str(e)}"

    updated_placeholders, message = _apply_rewrite_block(
        placeholders, block_id, new_content
    )
    state["filled_placeholders"] = updated_placeholders
    return message
