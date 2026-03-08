from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    model_name: str = "openai:gpt-4o"
    database_url: str = "sqlite+aiosqlite:///data/tickets.db"
    logfire_enabled: bool = False
    logfire_token: str = ""
    logfire_org: str = ""
    logfire_project: str = ""
    openai_api_key: str = ""


settings = Settings()
