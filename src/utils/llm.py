# src/utils/llm.py
from src.core.config import settings


def get_llm():
    """
    Returns LLM instance based on configured provider.
    Supports ollama, openai, and groq.
    """

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model      = settings.llm_model,
            api_key    = settings.openai_api_key,
            temperature= 0,
        )

    

    else:
        # Default — Ollama local
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model      = settings.llm_model,
            temperature= 0.3,
        )
