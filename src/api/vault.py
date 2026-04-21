from fastapi import APIRouter, HTTPException
from src.core.dependencies import supabase
from src.core.config import settings
from pydantic import BaseModel
import asyncio
import httpx
from src.utils.ginga_utils import render_blueprint_to_html


router = APIRouter(prefix="/vault", tags=["Vault"])
VAULT_QUERY_TIMEOUT_SECONDS = 15
RESULT_FETCH_TIMEOUT_SECONDS = 30
TEMPLATE_FETCH_TIMEOUT_SECONDS = 30


class RenderHtmlRequest(BaseModel):
    template_str: str
    placeholders: dict
    show_block_id: bool = False


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return True
    message = str(exc).lower()
    return "timed out" in message or "timeout" in message

async def get_user_vault(user_email: str):
    try:
        # 1. Clean the input (removes invisible spaces/tabs from the URL)
        # We keep the casing exactly as it is, per your request.
        clean_email = user_email.strip()

        url = f"{settings.supabase_url.rstrip('/')}/rest/v1/requests"
        headers = {
            "apikey": settings.supabase_key,
            "Authorization": f"Bearer {settings.supabase_key}",
        }
        params = {
            "select": "request_id,display_name,status",
            "user_id": f"eq.{clean_email}",
            "order": "created_at.desc",
            "limit": "200",
        }

        async with httpx.AsyncClient(timeout=VAULT_QUERY_TIMEOUT_SECONDS) as client:
            rest_response = await client.get(url, headers=headers, params=params)

        rest_response.raise_for_status()
        rows = rest_response.json()

        if not rows:
            print(f"No blueprints found for: {clean_email}")
            return []

        print(f"Found {len(rows)} blueprints for: {clean_email}")
        return rows

        # 3. Handle the "Empty" case
        if not response.data:
            print(f"ℹ️ No blueprints found for: {clean_email}")
            return [] # Return empty list so the frontend doesn't crash

        # 4. Handle Success
        print(f"✅ Found {len(response.data)} blueprints for: {clean_email}")
        return response.data

    except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
        print(f"Vault query timed out for: {clean_email}")
        raise HTTPException(
            status_code=504,
            detail=f"Vault query timed out after {VAULT_QUERY_TIMEOUT_SECONDS} seconds",
        )
    except httpx.RequestError as e:
        print(f"Vault network error for {clean_email}: {str(e)}")
        raise HTTPException(
            status_code=504,
            detail="Could not connect to Supabase for the vault request",
        )
    except httpx.HTTPStatusError as e:
        print(f"Vault REST error for {clean_email}: {e.response.status_code} {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail="Supabase rejected the vault request",
        )
    except Exception as e:
        # This helps you see the REAL error in your terminal
        print(f"❌ Supabase/Backend Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/result/{request_id}")
async def get_specific_result(request_id: str):
    try:
        def fetch_data():
            req = (
                supabase.table("requests")
                .select("display_name")
                .eq("request_id", request_id)
                .single()
                .execute()
            )

            # Prefer new column, fallback to old column if schema not migrated.
            try:
                bp = (
                    supabase.table("blueprints")
                    .select("placeholder_json, placeholders, filled_placeholders")
                    .eq("request_id", request_id)
                    .single()
                    .execute()
                )
            except Exception as err:
                if "placeholder_json" in str(err) and "does not exist" in str(err):
                    bp = (
                        supabase.table("blueprints")
                        .select("placeholders")
                        .eq("request_id", request_id)
                        .single()
                        .execute()
                    )
                elif "placeholders" in str(err) and "does not exist" in str(err):
                    bp = (
                        supabase.table("blueprints")
                        .select("placeholder_json")
                        .eq("request_id", request_id)
                        .single()
                        .execute()
                    )
                else:
                    raise

            return req, bp

        req_res, bp_res = await asyncio.wait_for(
            asyncio.to_thread(fetch_data),
            timeout=RESULT_FETCH_TIMEOUT_SECONDS,
        )

        if not req_res.data:
            raise HTTPException(status_code=404, detail="Request not found")
        if not bp_res.data:
            raise HTTPException(status_code=404, detail="Placeholder data not found")

        placeholder_json = bp_res.data.get("filled_placeholders")
        if placeholder_json is None:
            placeholder_json = bp_res.data.get("placeholder_json")
        if placeholder_json is None:
            placeholder_json = bp_res.data.get("placeholders", {})

        return {
            "display_name": req_res.data.get("display_name"),
            "placeholder_json": placeholder_json
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching specific result: {e}")
        if _is_timeout_error(e):
            raise HTTPException(
                status_code=504,
                detail="Result fetch timed out while reading Supabase",
            )
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error while fetching result"
        )

@router.delete("/{request_id}") # Corrected: Just the parameter
async def delete_request_and_blueprint(request_id: str):
    """
    Deletes the specific request and its associated blueprint from Supabase.
    """
    try:
        # 1. Delete from 'blueprints' (Child table)
        supabase.table("blueprints").delete().eq("request_id", request_id).execute()
        
        # 2. Delete from 'requests' (Parent table)
        response = supabase.table("requests").delete().eq("request_id", request_id).execute()

        if not response.data:
             return {"status": "info", "message": "ID not found or already deleted."}

        return {"status": "success", "message": f"Deleted {request_id}"}

    except Exception as e:
        print(f"❌ Delete Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error during deletion")
    


@router.get("/result/{request_id}/templates")
async def get_all_templates(request_id: str):
    """
    Fetches all .ginja files from Supabase Storage for a specific request.
    Path: opandz-assets/{request_id}/templates/*.ginja
    """
    folder_path = f"{request_id}/templates"

    def fetch_templates():
        bucket = supabase.storage.from_("opandz-assets")
        files = bucket.list(path=folder_path)
        if not files:
            return {}

        all_templates = {}
        for file_info in files:
            file_name = file_info.get("name", "")
            if not file_name.endswith(".ginja"):
                continue

            page_key = file_name.replace(".ginja", "")
            full_path = f"{folder_path}/{file_name}"
            content_bytes = bucket.download(full_path)
            all_templates[page_key] = content_bytes.decode("utf-8")
        return all_templates

    try:
        all_templates = await asyncio.wait_for(
            asyncio.to_thread(fetch_templates),
            timeout=TEMPLATE_FETCH_TIMEOUT_SECONDS,
        )

        return {
            "request_id": request_id,
            "templates": all_templates
        }

    except Exception as e:
        print(f"❌ Error fetching templates from Supabase: {e}")
        if _is_timeout_error(e):
            raise HTTPException(
                status_code=504,
                detail="Template fetch timed out while reading Supabase Storage",
            )
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error while fetching templates",
        )

@router.post("/render-html")
async def render_template_html(payload: RenderHtmlRequest):
    """
    Render one Ginja template to final HTML using placeholder_json data.
    """
    try:
        html = render_blueprint_to_html(
            payload.template_str,
            payload.placeholders,
            show_block_id=payload.show_block_id,
        )
        return {"html": html}
    except Exception as e:
        print(f"Error rendering template HTML: {e}")
        raise HTTPException(status_code=500, detail="Failed to render HTML")


@router.get("/{user_email}")
async def list_user_vault(user_email: str):
    return await get_user_vault(user_email)

