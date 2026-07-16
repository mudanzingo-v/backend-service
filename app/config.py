"""
Application settings — loaded from environment variables (.env).
"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: Literal["local", "dev", "staging", "prod"] = "local"
    app_name: str = "mobbit-backend-service"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Database
    database_url: str = "postgresql+asyncpg://mobbit:mobbit@db:5432/mobbit"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # Auth (Cognito)
    aws_region: str = "us-west-2"
    cognito_user_pool_mobbit: str = "us-west-2_1h3mHs8GJ"
    cognito_user_pool_providers: str = "us-west-2_fwzhDEy8q"
    cognito_user_pool_rccm: str = "us-west-2_M9NJljg8s"
    cognito_client_mobbit: str = "client_mobbit"
    cognito_client_providers: str = "client_providers"
    cognito_client_rccm: str = "client_rccm"
    auth_skip_verification: bool = False
    # In dev mode, when the JWT has `sub="dev-provider"`, substitute
    # this provider id. Lets the front-provider app demo as a real
    # provider without setting up Cognito. Set to a provider id from
    # the `providers` table.
    dev_provider_id: str = "678ff2ad-e184-42e4-9dcf-f9962f4487a9"

    # External services
    b2c_frontend_url: str = "http://localhost:3051"
    copomex_api_token: str = ""
    copomex_api_url: str = "https://api.copomex.com"

    # Payments (Stripe)
    # Empty stripe_secret_key + is_local=True triggers mock mode in app/services/stripe.py
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_version: str = "2024-06-20"

    # Email (SMTP)
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@mobbit.mx"
    smtp_use_tls: bool = False
    
    # Pricing model
    pricing_mobbit_fee: float = 0.05
    pricing_iva: float = 0.16
    pricing_transaction_fee: float = 0.05
    pricing_cash_on_delivery_provider_fee: float = 0.85
    pricing_cash_on_delivery_mobbit_fee: float = 0.15
    
    # CORS
    cors_allow_origins: str = "http://localhost:3000,http://localhost:5173"

    @field_validator("cors_allow_origins")
    @classmethod
    def _validate_cors(cls, v: str) -> str:
        # Allow either a JSON array string or a comma-separated list
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def is_local(self) -> bool:
        return self.app_env in ("local", "dev")

    def cognito_jwks_url(self, user_pool_id: str) -> str:
        """JWKS endpoint for a Cognito user pool."""
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"

    def cognito_issuer(self, user_pool_id: str) -> str:
        """Issuer URL for a Cognito user pool (used to validate `iss` claim)."""
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{user_pool_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
