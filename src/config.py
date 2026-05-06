from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    model_name: str = "openai:gpt-4o"
    database_url: str = "sqlite+aiosqlite:///data/tickets.db"
    openai_api_key: str = ""
    app_base_url: str = "http://localhost:8000"
    pms_status_base_url: str = "http://localhost:8001"


settings = Settings()
