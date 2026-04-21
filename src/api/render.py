from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import asyncio
import os
import tempfile

from src.core.dependencies import supabase

router = APIRouter(prefix="/render", tags=["render"])


def _filled_blueprint_to_placeholders(filled_blueprint: dict) -> dict:
    placeholders = {}
    for page in filled_blueprint.get("pages", []):
        for block in page.get("blocks", []):
            block_id = str(block.get("block_id", ""))
            if not block_id:
                continue
            placeholders[block_id] = {
                "label": block.get("label", ""),
                "sub_label": block.get("sub_label", ""),
                "content": block.get("content", ""),
            }
    return placeholders


@router.get("/download-pdf/{request_id}")
async def download_pdf(request_id: str):

    try:
        # 🔹 1. Fetch data from Supabase
        def fetch_data():
            return (
                supabase.table("blueprints")
                .select("blueprint_json, placeholders, filled_placeholders")
                .eq("request_id", request_id)
                .single()
                .execute()
            )

        res = await asyncio.to_thread(fetch_data)

        if not res.data:
            raise HTTPException(status_code=404, detail="Data not found")

        blueprint_json = res.data.get("blueprint_json")
        filled_blueprint = res.data.get("filled_placeholders")
        filled_json = (
            _filled_blueprint_to_placeholders(filled_blueprint)
            if isinstance(filled_blueprint, dict) and isinstance(filled_blueprint.get("pages"), list)
            else filled_blueprint
        )
        if not filled_json:
            filled_json = res.data.get("placeholders")

        if not blueprint_json:
            raise HTTPException(status_code=400, detail="Blueprint missing")

        if not filled_json:
            raise HTTPException(status_code=400, detail="Filled data missing")

        # 🔹 2. Generate PDF path
        try:
            from src.utils.pdf_renderer import render_to_pdf
        except ModuleNotFoundError as e:
            if e.name == "reportlab":
                raise HTTPException(
                    status_code=500,
                    detail="PDF renderer dependency missing: install reportlab",
                )
            raise

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf",
            prefix=f"{request_id}_",
        )
        output_path = temp_file.name
        temp_file.close()

        # 🔹 3. Render PDF
        await asyncio.to_thread(
            render_to_pdf,
            blueprint_json,
            filled_json,
            output_path
        )

        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="PDF generation failed")

        # 🔹 4. Return PDF
        return FileResponse(
            path=output_path,
            filename=f"{request_id}.pdf",
            media_type="application/pdf",
            background=BackgroundTask(lambda: os.path.exists(output_path) and os.remove(output_path)),
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"PDF error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error"
        )
