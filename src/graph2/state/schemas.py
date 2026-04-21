from typing import Any, Dict, List
from typing_extensions import TypedDict


# 🔹 Content-only block
class FilledPlaceholder(TypedDict):
    label: str
    sub_label: str
    content: str


# 🔹 Flat mapping: block_id → content
FilledPlaceholders = Dict[str, FilledPlaceholder]


# 🔹 FINAL STATE (NO blueprint)
class WriterState(TypedDict):
    request_id: str
    user_query: str

    filled_placeholders: FilledPlaceholders

    messages: List[Any]
    errors: List[str]