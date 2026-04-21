import asyncio
import re
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr
from src.core.dependencies import supabase 

router = APIRouter(prefix="/extract", tags=["Extraction"])

class ExtractionRequest(BaseModel):
    request_id: str
    display_name: str
    user_email: EmailStr
    storage_path: str

def safe_filename(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name or "document.pdf"

async def run_graph_task(request_id: str, storage_path: str):
    """
    Background worker: Processes the AI Graph.
    Uses an event loop friendly way to call synchronous Supabase methods.
    """
    loop = asyncio.get_event_loop()
    
    try:
        print(f"--- [STARTING GRAPH] Request: {request_id} ---")
        from src.graph1.graph import extraction_graph
        
        initial_state = {
            "pdf_file": storage_path,
            "request_id": request_id,
            "pages": [],
            "errors": []
        }
        
        # 1. Start the LangGraph execution (Async)
        await extraction_graph.ainvoke(initial_state)
        
        print(f"✅ AI processing completed for {request_id}")

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Graph Critical Failure for {request_id}: {error_msg}")
        
        # 2. Sync-to-Async wrapper for the failure update
        # This prevents the synchronous .execute() from freezing the async loop
        def update_failure():
            return supabase.table("requests").update({
                "status": "failed",
                "error_log": f"Graph Failure: {error_msg}" # Ensure this column exists!
            }).eq("request_id", request_id).execute()

        await loop.run_in_executor(None, update_failure)

@router.post("/")
async def start_extraction(
    data: ExtractionRequest, 
    background_tasks: BackgroundTasks
):
    try:
        # 1. Create the database record (Synchronous)
        # We wrap this to keep the entry point fast
        def create_record():
            return supabase.table("requests").insert({
                "request_id": data.request_id,
                "display_name": data.display_name,
                "user_id": data.user_email,
                "status": "processing"
            }).execute()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, create_record)

        # 2. Add the AI Graph task to the background
        background_tasks.add_task(run_graph_task, data.request_id, data.storage_path)

        return {
            "status": "accepted",
            "request_id": data.request_id,
            "message": "AI background process initiated."
        }

    except Exception as e:
        print(f"🔥 Server Error during registration: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/upload")
async def upload_and_start_extraction(
    background_tasks: BackgroundTasks,
    display_name: str = Form(...),
    user_email: EmailStr = Form(...),
    file: UploadFile = File(...)
):
    if file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    request_id = str(uuid4())
    filename = safe_filename(file.filename or "document.pdf")
    storage_path = f"{request_id}/source/{filename}"

    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

        def upload_and_create_record():
            supabase.storage.from_("opandz-assets").upload(
                path=storage_path,
                file=file_bytes,
                file_options={"content-type": "application/pdf", "upsert": "false"}
            )
            return supabase.table("requests").insert({
                "request_id": request_id,
                "display_name": display_name.strip() or filename,
                "user_id": str(user_email),
                "status": "processing"
            }).execute()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, upload_and_create_record)

        background_tasks.add_task(run_graph_task, request_id, storage_path)

        return {
            "status": "accepted",
            "request_id": request_id,
            "storage_path": storage_path,
            "message": "PDF uploaded and AI background process initiated."
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Upload/start extraction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Upload/start extraction failed: {str(e)}"
        )
