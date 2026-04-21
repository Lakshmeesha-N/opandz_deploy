import os
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
# Assuming your routers are in src/api/
from src.api import agent_edit, extraction, render, vault

app = FastAPI()

# --- DYNAMIC PATH LOGIC ---
# This points to the root of OPANDZ_DEPLOY
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

static_path = os.path.join(BASE_DIR, "frontend", "static")
template_path = os.path.join(BASE_DIR, "frontend", "templates")

# --- MOUNTING ---
# Ensure these folders exist in /frontend/
app.mount("/static", StaticFiles(directory=static_path), name="static")
templates = Jinja2Templates(directory=template_path)

# --- INCLUDE YOUR API ROUTERS ---
app.include_router(extraction.router)
app.include_router(vault.router)
app.include_router(agent_edit.router)
app.include_router(render.router)

# --- UI ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    """Serves the main Vault UI."""
    return templates.TemplateResponse(
        request=request,
        name="vault.html",
        context={"request": request}
    )

@app.get("/upload", response_class=HTMLResponse)
async def serve_upload(request: Request):
    """Serves the Upload UI."""
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"request": request}
    )

@app.get("/view/{request_id}", response_class=HTMLResponse)
async def serve_viewer(request: Request, request_id: str):
    """Serves the 50/50 Preview/Workspace UI."""
    # Note: In production, you'd fetch the actual blueprint data here 
    # from Supabase and pass it into the context below.
    return templates.TemplateResponse(
        request=request,
        name="viewer.html",
        context={
            "request": request, 
            "request_id": request_id,
            "blueprint": {}, # Pass extracted data here
            "templates": {}  # Pass page HTML here
        }
    )
