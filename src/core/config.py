class Settings(BaseSettings):
    # --- LLM CONFIG ---
    llm_provider: str = "openai"   # default, overridden by .env
    llm_model: str = "gpt-4.1-nano"

    # --- API KEYS ---
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # --- DATABASE ---
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    supabase_anon_key: Optional[str] = None

    # --- PATHS ---
    model_dir: Path = PROJECT_ROOT / "modles"
    yolo_model_path: str = str(model_dir / "yolov8_custom_best.pt")
    lilt_model_path: str = "Lakshmeesha/opandz-lilt-finetuned"

    # --- PROCESSING ---
    max_pages: int = 10
    image_zoom: float = 2.0
    yolo_confidence_threshold: float = 0.5
    yolo_iou_threshold: float = 0.3

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
