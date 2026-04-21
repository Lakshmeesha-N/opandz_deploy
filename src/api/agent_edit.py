from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio
import copy
from src.core.dependencies import supabase
from src.graph2.graph import writer_graph

router = APIRouter()
AGENT_EDIT_FETCH_TIMEOUT_SECONDS = 25
AGENT_EDIT_GRAPH_TIMEOUT_SECONDS = 90
AGENT_EDIT_UPDATE_TIMEOUT_SECONDS = 25


# 🔹 Request model
class AgentEditRequest(BaseModel):
    user_query: str
    mode: str = "continue"   # "continue" | "new"


def _build_filled_blueprint(blueprint_json: dict, placeholders: dict) -> dict:
    filled_blueprint = {
        "total_pages": blueprint_json.get("total_pages", 0),
        "pages": [],
    }

    for page in blueprint_json.get("pages", []):
        filled_page = {
            **page,
            "blocks": [],
        }

        for block in page.get("blocks", []):
            block_id = str(block.get("block_id", ""))
            placeholder = placeholders.get(block_id, {}) or {}
            filled_page["blocks"].append({
                **block,
                "block_id": block_id,
                "label": placeholder.get("label", block.get("label", "")),
                "sub_label": placeholder.get("sub_label", block.get("sub_label", "")),
                "content": placeholder.get("content", block.get("content", "")),
            })

        filled_blueprint["pages"].append(filled_page)

    return filled_blueprint


def _ensure_filled_blueprint(candidate: dict, blueprint_json: dict, placeholders: dict) -> dict:
    if isinstance(candidate, dict) and isinstance(candidate.get("pages"), list):
        return candidate
    return _build_filled_blueprint(blueprint_json, placeholders)


def _filled_blueprint_to_placeholders(filled_blueprint: dict) -> dict:
    placeholder_json = {}
    for page in filled_blueprint.get("pages", []):
        for block in page.get("blocks", []):
            block_id = str(block.get("block_id", ""))
            if not block_id:
                continue
            placeholder_json[block_id] = {
                "label": block.get("label", ""),
                "sub_label": block.get("sub_label", ""),
                "content": block.get("content", ""),
            }
    return placeholder_json


def _message_to_text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    message = str(exc).lower()
    return "timed out" in message or "timeout" in message


async def _run_writer_graph(
    request_id: str,
    user_query: str,
    filled_placeholders: dict,
) -> dict:
    print(f"[agent-edit] running Graph 2 for request_id={request_id}")
    return await asyncio.wait_for(
        asyncio.to_thread(
            writer_graph.invoke,
            {
                "request_id": request_id,
                "filled_placeholders": filled_placeholders,
                "user_query": user_query,
                "messages": [],
                "errors": [],
            },
        ),
        timeout=AGENT_EDIT_GRAPH_TIMEOUT_SECONDS,
    )


async def _save_filled_placeholders(request_id: str, updated_json: dict):
    print(f"[agent-edit] saving filled_placeholders for request_id={request_id}")

    def update_data():
        return supabase.table("blueprints").update({
            "filled_placeholders": updated_json
        }).eq("request_id", request_id).execute()

    return await asyncio.wait_for(
        asyncio.to_thread(update_data),
        timeout=AGENT_EDIT_UPDATE_TIMEOUT_SECONDS,
    )


@router.post("/agent-edit/{request_id}")
async def agent_edit(request_id: str, payload: AgentEditRequest):

    try:
        user_query = payload.user_query
        mode = payload.mode

        # 🔹 1. Fetch both template + filled
        def fetch_data():
            return (
                supabase.table("blueprints")
                .select("blueprint_json, placeholders, filled_placeholders")
                .eq("request_id", request_id)
                .single()
                .execute()
            )

        print(f"[agent-edit] fetching blueprint for request_id={request_id}")
        bp_res = await asyncio.wait_for(
            asyncio.to_thread(fetch_data),
            timeout=AGENT_EDIT_FETCH_TIMEOUT_SECONDS,
        )
        print(f"[agent-edit] fetched blueprint for request_id={request_id}")

        if not bp_res.data:
            raise HTTPException(status_code=404, detail="Data not found")

        blueprint_json = bp_res.data.get("blueprint_json", {}) or {}
        placeholders = bp_res.data.get("placeholders", {}) or {}
        filled = bp_res.data.get("filled_placeholders")

        if not filled:
            filled_placeholders = copy.deepcopy(placeholders)

            result = await _run_writer_graph(
                request_id,
                user_query,
                filled_placeholders,
            )

            updated_json = result.get("filled_placeholders", filled_placeholders)

            await _save_filled_placeholders(request_id, updated_json)
            print(f"[agent-edit] saved filled_placeholders for request_id={request_id}")

            return {
                "messages": [_message_to_text(message) for message in result.get("messages", [])],
                "placeholder_json": updated_json
            }

        # 🔹 2. Decide which data to use

        if mode == "new":
            filled_placeholders = copy.deepcopy(placeholders)

        elif isinstance(filled, dict) and isinstance(filled.get("pages"), list):
            filled_placeholders = _filled_blueprint_to_placeholders(filled)

        else:
            filled_placeholders = copy.deepcopy(filled)

        # 🔹 3. Run graph
        result = await _run_writer_graph(
            request_id,
            user_query,
            filled_placeholders,
        )

        updated_json = result.get("filled_placeholders", filled_placeholders)

        # 🔹 4. Save updated JSON
        await _save_filled_placeholders(request_id, updated_json)
        print(f"[agent-edit] saved filled_placeholders for request_id={request_id}")

        # 🔹 5. Return response
        return {
            "messages": [_message_to_text(message) for message in result.get("messages", [])],
            "placeholder_json": updated_json
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in agent-edit: {e}")
        if _is_timeout_error(e):
            raise HTTPException(
                status_code=504,
                detail="Agent edit timed out while fetching, editing, or saving data"
            )
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error"
        )
