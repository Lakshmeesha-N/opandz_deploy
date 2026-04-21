import re
from html import escape

from jinja2 import Template


_NUMERIC_PLACEHOLDER_EXPR = re.compile(r"{{\s*(\d+_\d+)(\s*(?:\|[^}]*)?)}}")


def _placeholder_value(data) -> str:
    if isinstance(data, dict):
        return str(data.get("content", "") or "")
    if data is None:
        return ""
    return str(data)


def _alias_numeric_placeholders(template_str: str, render_context: dict) -> str:
    """
    Jinja treats {{ 1_1 }} as the numeric literal 11, not as a variable name.
    Convert numeric block placeholders to valid aliases before rendering.
    """
    def replace(match: re.Match) -> str:
        block_id = match.group(1)
        filters = match.group(2) or ""
        alias = f"__block_{block_id.replace('_', '_')}"
        render_context[alias] = render_context.get(block_id, "")
        return "{{ " + alias + filters + " }}"

    return _NUMERIC_PLACEHOLDER_EXPR.sub(replace, template_str)

def render_blueprint_to_html(template_str: str, placeholders: dict, show_block_id: bool = False) -> str:
    render_context = {}

    for block_id, data in (placeholders or {}).items():
        content = escape(_placeholder_value(data), quote=False)

        # 🔴 ADD THIS PART
        if show_block_id:
            content = (
                f"<span style='color:red; font-size:6px; font-weight:bold;'>"
                f"[{block_id}] </span>{content}"
            )

        render_context[str(block_id)] = content

    aliased_template = _alias_numeric_placeholders(template_str, render_context)
    template = Template(aliased_template)
    return template.render(**render_context)
