from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.gateway import gateway_provider

from src.config import settings

llm_model = OpenAIChatModel(
    settings.model_name,
    provider=gateway_provider("openai", route="openai-fallback"),
)
