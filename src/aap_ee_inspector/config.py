"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AAP connection settings, loaded from environment variables or `.env`.

    aap_api_token: Bearer token used to authenticate against the AAP controller API.
    aap_base_url: Hostname of the AAP controller (no scheme, e.g. "aap.example.com").
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aap_api_token: str
    aap_base_url: str
