import json
import re
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from typing_extensions import Annotated

from state.schemas import WriterState
from tools.change_block_tool import change_block, _apply_block_change
from tools.rewrite_all_tool import rewrite_all
from tools.rewrite_block_tool import  rewrite_block, _find_block ,_build_rewrite_prompt, _apply_rewrite_block , _apply_rewrite_block
from utils.llm import get_llm 


TOOLS = [rewrite_block, rewrite_all, change_block]


def _is_help_query(user_query: str) -> bool:
    normalized = user_query.lower().strip(" .?!")
    return normalized in {
        "hi",
        "hello",
        "hey",
        "help",
        "how can you help me",
        "what can you do",
    }


def _help_message() -> str:
    return (
        "I can rewrite the whole document, rewrite a specific block by its preview ID, "
        "or change header/footer text.\n\n"
        "Note: The red‑colored block IDs shown in the preview are only for reference; "
        "they do not appear in the final document. Some text may look less visible in the preview "
        "but will be fully visible in the final version.\n\n"
        "To change header or footer text, use commands like: "
        "'change left header to ...', 'change right header to ...', 'change center header to ...', "
        "and the same applies for footer.\n\n"
        "For blocks, mention the block ID and your instruction, e.g.: "
        "'change block 1_5 to new topic'."
    )





def _build_system_prompt() -> str:
    return (
        "IMPORTANT: Call ONLY ONE tool per user request. Never call multiple tools at once.\n"
        "You are a document editing assistant.\n\n"
        "The user can see the document preview with block IDs marked on screen.\n\n"
        "Available tools:\n"
        "- change_block: change header or footer text\n"
        "  params: region (header/footer), side (left/right/center/all), value\n"
        "- rewrite_block: rewrite a specific block\n"
        "  params: block_id (user provides from preview), instruction\n"
        "- rewrite_all: rewrite entire document\n"
        "  params: instruction\n\n"
        "Guidelines:\n"
        "- If the user gives a block ID like 1_3, call rewrite_block, not rewrite_all.\n"
        "- Use rewrite_all only when the user clearly asks for the whole document/all blocks.\n"
        "- If the user says change header, ask which side: left, right, center, or all.\n"
        "- If the user says change a block but gives no block_id, ask them to check the preview.\n"
        "- Keep responses short and friendly.\n"
        "- Never output custom tags like <function=...>. Use native tool calls only.\n"
    )


def _limit_to_one_tool_call(response: AIMessage) -> AIMessage:
    tool_calls = getattr(response, "tool_calls", None) or []
    if len(tool_calls) <= 1:
        return response

    additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
    if isinstance(additional_kwargs.get("tool_calls"), list):
        additional_kwargs["tool_calls"] = additional_kwargs["tool_calls"][:1]

    limited = response.model_copy(
        update={
            "tool_calls": tool_calls[:1],
            "additional_kwargs": additional_kwargs,
        }
    )
    print(
        f"[agent_node] Trimmed tool calls from {len(tool_calls)} to 1: "
        f"{[tc['name'] for tc in limited.tool_calls]}"
    )
    return limited


def _parse_tool_from_content(content: str) -> tuple[str, dict] | None:
    """
    Parse tool calls from models that emit tool calls as plain text.
    Handles:
    1. [{"name": "rewrite_block", "arguments": {...}}]
    2. [rewrite_block(block_id="1_3", instruction="make it formal")]
    """
    try:
        cleaned = content.split("<|/tool_call|>")[0].strip()

        json_match = re.search(r'\[\s*\{"name".*?\}\s*\]', cleaned, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            tool_name = parsed[0].get("name", "")
            tool_args = parsed[0].get("arguments", parsed[0].get("args", {}))
            if tool_name:
                return tool_name, tool_args

        func_match = re.search(r"\[(\w+)\((.*?)\)\]", cleaned, re.DOTALL)
        if func_match:
            tool_name = func_match.group(1)
            args_str = func_match.group(2)
            tool_args = {}
            for match in re.finditer(r'(\w+)\s*=\s*["\']([^"\']*)["\']', args_str):
                tool_args[match.group(1)] = match.group(2)
            for match in re.finditer(r"(\w+)\s*=\s*(\d+)", args_str):
                tool_args[match.group(1)] = int(match.group(2))
            if tool_name:
                return tool_name, tool_args
    except Exception as e:
        print(f"[agent_node] Tool parse failed: {e}")

    return None


def _execute_parsed_tool(
    tool_name: str,
    tool_args: dict,
    state: WriterState,
    messages: list,
    user_query: str,
) -> dict | None:
    filled_placeholders = state["filled_placeholders"]

    try:
        if tool_name == "change_block":
            updated, msg = _apply_block_change(
                filled_placeholders,
                region=tool_args.get("region", "header"),
                side=tool_args.get("side", "all"),
                value=tool_args.get("value", ""),
            )
            state["filled_placeholders"] = updated

        elif tool_name == "rewrite_block":
            block_id = str(tool_args.get("block_id", ""))
            instruction = tool_args.get("instruction", tool_args.get("new_content", ""))
            block = _find_block(filled_placeholders, block_id)

            if block is None:
                updated, msg = filled_placeholders, f"Block '{block_id}' not found."
            elif block.get("label") == "PAGE_INFO":
                updated, msg = filled_placeholders, f"Block '{block_id}' is header/footer. Use change_block."
            else:
                response = get_llm().invoke(_build_rewrite_prompt(block, instruction))
                updated, msg = _apply_rewrite_block(
                    filled_placeholders,
                    block_id=block_id,
                    new_content=response.content.strip(),
                )
            state["filled_placeholders"] = updated

        elif tool_name == "rewrite_all":
            msg = rewrite_all.invoke({
                "instruction": tool_args.get("instruction", ""),
                "state": state,
            })

        else:
            return None

        print(f"[agent_node] Manual {tool_name}: {msg}")
        return {
            "filled_placeholders": state["filled_placeholders"],
            "messages": messages + [
                HumanMessage(content=user_query),
                AIMessage(content=f"Done. {msg}"),
            ],
            "errors": state.get("errors", []),
        }

    except Exception as e:
        print(f"[agent_node] Manual tool execution failed: {e}")
        return {
            "filled_placeholders": filled_placeholders,
            "messages": messages + [
                HumanMessage(content=user_query),
                AIMessage(content=f"I could not run {tool_name}: {e}"),
            ],
            "errors": state.get("errors", []) + [str(e)],
        }


def agent_node(state: WriterState) -> dict:
    """
    LLM agent node for Graph 2.

    Handles native tool_calls through LangGraph ToolNode and manual text-form
    tool calls from local/Ollama-style models.
    """
    filled_placeholders = state.get("filled_placeholders", {}) or {}
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    user_query = state.get("user_query", "")

    print(f"[agent_node] User query: {user_query}")
    
    # --- No placeholders case ---
    if not filled_placeholders:
        messages.append(AIMessage(content="No filled placeholders were available to edit."))
        return {
            "filled_placeholders": filled_placeholders,
            "messages": messages,
            "errors": errors,
        }

    # --- Help query case ---
    if _is_help_query(user_query):
        messages.append(AIMessage(content=_help_message()))
        return {
            "filled_placeholders": filled_placeholders,
            "messages": messages,
            "errors": errors,
        }

    # --- ToolMessage case ---
    if messages:
        last_msg = messages[-1]
        if last_msg.__class__.__name__ == "ToolMessage":
            return {
                "filled_placeholders": filled_placeholders,
                "messages": messages + [AIMessage(content=f"Done. {last_msg.content}")],
                "errors": errors,
            }

    # --- LLM tool binding + invocation ---
    try:
        llm_tools = get_llm().bind_tools(TOOLS)
        llm_messages = [
            SystemMessage(content=_build_system_prompt()),
            HumanMessage(content=user_query),
        ]

        response = _limit_to_one_tool_call(llm_tools.invoke(llm_messages))

        print(f"[agent_node] DEBUG tool_calls: {getattr(response, 'tool_calls', None)}")
        print(f"[agent_node] DEBUG content: {str(response.content)[:200]}")

        if response.tool_calls:
            print(f"[agent_node] LLM calling tools: {[tc['name'] for tc in response.tool_calls]}")
            return {
                "filled_placeholders": filled_placeholders,
                "messages": messages + [HumanMessage(content=user_query), response],
                "errors": errors,
            }

        if response.content:
            parsed = _parse_tool_from_content(str(response.content))
            if parsed:
                tool_name, tool_args = parsed
                print(f"[agent_node] Manual tool parse: {tool_name} {tool_args}")
                result = _execute_parsed_tool(tool_name, tool_args, state, messages, user_query)
                if result:
                    return result

        return {
            "filled_placeholders": filled_placeholders,
            "messages": messages + [HumanMessage(content=user_query), response],
            "errors": errors,
        }

    except Exception as e:
        errors.append(str(e))
        messages.append(AIMessage(content=f"I could not update the filled placeholders: {e}"))
        print(f"[agent_node] Exception: {e}")
        return {
            "filled_placeholders": filled_placeholders,
            "messages": messages,
            "errors": errors,
        }

