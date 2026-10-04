"""
Application configuration.

All settings are loaded from .env via pydantic-settings.
This is the SINGLE SOURCE OF TRUTH for all configurable values.

fail-fast: required fields (no default) raise at startup if missing.
"""

import secrets
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Business Identity ---
    app_name: str = "House of Desserts"
    app_tagline: str = "Artisan Bakes & Cakes"
    fssai_number: str = ""
    gstin: str = ""
    phone: str = ""
    address: str = ""
    email: str = ""
    currency: str = "₹"

    # --- Application ---
    debug: bool = False
    secret_key: str = ""
    db_url: str = "sqlite:///data/bakery.db"
    business_timezone: str = "Asia/Kolkata"

    # --- Server ---
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000

    # --- WhatsApp / Messaging ---
    whatsapp_enabled: bool = True
    whatsapp_default_country_code: str = "91"
    whatsapp_messages_file: str = "config/messages.json"

    # --- Printer ---
    printer_type: str = "file"  # "usb" | "network" | "file"
    printer_device: str = ""
    printer_width: int = 80

    # --- Backup ---
    backup_dir: str = "./backups"
    backup_schedule: str = "daily"

    # --- Reports ---
    reports_dir: str = "./reports"

    # --- Invoice Numbering ---
    invoice_prefix: str = "HOD"
    invoice_start_number: int = 1

    @field_validator("secret_key")
    @classmethod
    def _ensure_secret(cls, v: str, info):
        if v:
            return v
        # No SECRET_KEY provided.
        # In production (DEBUG=false) this is unsafe: an ephemeral key would
        # invalidate every session on restart and could be used to forge
        # sessions across restarts. Fail fast instead.
        debug = info.data.get("debug", False)
        if not debug:
            raise ValueError(
                "SECRET_KEY is required when DEBUG=false. "
                "Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        # Dev only: generate an ephemeral key so local runs work out of the box.
        return secrets.token_urlsafe(32)

    @field_validator("printer_type")
    @classmethod
    def _validate_printer(cls, v: str) -> str:
        allowed = {"usb", "network", "file"}
        if v not in allowed:
            raise ValueError(f"printer_type must be one of {allowed}, got {v!r}")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
