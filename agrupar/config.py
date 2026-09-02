from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
GroupingUnit = Literal["gender", "gender_brand_model"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    meli_access_token: str = ""
    dry_run: bool = True
    revalidacao_segundos: int = Field(default=45, ge=0)
    revalidacao_intervalo_segundos: int = Field(default=5, ge=1)
    meli_concurrency: int = Field(default=10, ge=1, le=20)
    grouping_unit: GroupingUnit = "gender_brand_model"
    mlbs_file: Path = ROOT_DIR / "data" / "mlbs.txt"
    reports_dir: Path = ROOT_DIR / "reports"
    tentar_family_name_com_vendas: bool = False
    expandir_irmaos: bool = True
    genero_forcado: str = ""
    family_name_forcado: str = ""
    anymarket_db_host: str = ""
    anymarket_db_port: int = Field(default=5432, ge=1, le=65535)
    anymarket_db_name: str = "anymarket"
    anymarket_db_user: str = ""
    anymarket_db_password: str = ""
    anymarket_db_sslmode: str = "require"
    anymarket_oi: str = "259062760."


def missing_runtime_info(settings: Settings) -> list[str]:
    faltando: list[str] = []
    if not settings.meli_access_token.strip():
        faltando.append("MELI_ACCESS_TOKEN — token de aplicação do Mercado Livre.")
    return faltando
