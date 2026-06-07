from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    RATE_LIMITING_ENABLE: bool = True
    # Self-hosted Single-User-Instanz: Original-Default "2/3seconds" ist fuer
    # oeffentliche Multi-User-APIs gedacht und drosselt hier nur die eigenen Crons
    # (AdvisorWatch 8 parallel etc.) auf einem localhost-Bucket -> HTTP 429.
    # 30/second laesst die eigene Last durch, behaelt aber einen Runaway-Backstop.
    # Echte TM-Schonung uebernimmt der Client-Cache/SWR in transfermarktApi.js.
    RATE_LIMITING_FREQUENCY: str = "30/second"


settings = Settings()
