from __future__ import annotations

import httpx
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.gateway import gateway_provider

from src.config import settings

# Custom headers appear on the PAIG span as
# `attributes->>'http.request.header.<lowercased-name>'` — group dashboards on them.
_gateway_http_client = httpx.AsyncClient(
    headers={
        "X-Demo-Tenant": "csm-ticketing",
        "X-Cost-Center": "support-eng",
    },
)

llm_model = OpenAIChatModel(
    settings.model_name,
    provider=gateway_provider(
        "openai",
        route="openai-fallback",
        http_client=_gateway_http_client,
    ),
)
