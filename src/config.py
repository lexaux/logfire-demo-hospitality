from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    model_name: str = "gpt-4o"
    database_url: str = "sqlite+aiosqlite:///data/tickets.db"
    openai_api_key: str = ""
    app_base_url: str = "http://localhost:8000"
    status_service_base_url: str = "http://localhost:8001"
    logfire_api_key: str = ""
    # Public-by-design write token shipped to the browser for OTel ingestion.
    # In prod use a token-vending endpoint instead.
    logfire_browser_write_token: str = ""
    logfire_otlp_endpoint: str = "https://logfire-api.pydantic.dev/v1/traces"


settings = Settings()
