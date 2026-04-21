from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing import Optional
from typing_extensions import Annotated
from src.graph2.state.schemas import WriterState


def _apply_block_change(
    filled_placeholders: dict,
    region: str,
    side: str,
    value: str,
) -> tuple[dict, str]:
    """
    Core logic — updates blocks based on sub_label in flat structure.
    """

    region = region.lower().strip()
    side = side.lower().strip()

    prefix = f"{region.upper()}_"

    # Determine targets
    if side == "all":
        targets = {
            f"{prefix}LEFT",
            f"{prefix}RIGHT",
            f"{prefix}CENTER",
        }
    else:
        targets = {f"{prefix}{side.upper()}"}

    changed_count = 0

    # 🔹 Loop through flat dict
    for block_id, block in filled_placeholders.items():
        sub_label = block.get("sub_label", "")

        if sub_label in targets:
            block["content"] = value
            changed_count += 1

    message = (
        f"✓ Changed {region} ({side}) to '{value}' — {changed_count} block(s) updated."
        if changed_count > 0
        else f"✗ No {region} ({side}) blocks found."
    )

    return filled_placeholders, message


@tool
def change_block(
    region: str,
    side: str,
    value: str,
    state: Annotated[WriterState, InjectedState] = None,
) -> str:
    """
    Change header or footer text in the document (flat schema).

    Args:
        region: header or footer
        side: left, right, center, or all
        value: new text
    """

    filled_placeholders = state["filled_placeholders"]

    updated, message = _apply_block_change(
        filled_placeholders,
        region,
        side,
        value,
    )

    state["filled_placeholders"] = updated

    return message