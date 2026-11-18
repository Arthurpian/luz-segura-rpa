"""Contrato de entrada do robô (o que o app do cidadão grava na caixa de entrada)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

Rotulo = Literal["adequada", "fraca", "inexistente"]
FUSO_PADRAO = ZoneInfo("America/Sao_Paulo")


class ClassificacaoVisao(BaseModel):
    """Resultado do componente de Visão Computacional (ou do fallback)."""
    rotulo: Rotulo
    confianca: float = Field(ge=0.0, le=1.0)
    fonte: str = "app_visao"


class RelatoEntrada(BaseModel):
    """Relato enviado pelo cidadão: foto noturna + localização."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    criado_em: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    foto: str = Field(min_length=1, max_length=200)
    descricao: str | None = Field(default=None, max_length=500)
    contato: str | None = Field(default=None, max_length=120)
    canal: Literal["app", "web", "whatsapp", "totem"] = "app"
    classificacao_visao: ClassificacaoVisao | None = None

    @field_validator("criado_em")
    @classmethod
    def _garantir_fuso(cls, valor: datetime) -> datetime:
        # Relato sem fuso é interpretado no horário de Brasília
        return valor if valor.tzinfo else valor.replace(tzinfo=FUSO_PADRAO)

    @field_validator("foto")
    @classmethod
    def _bloquear_caminho(cls, valor: str) -> str:
        # Segurança: impede path traversal ("../../etc/passwd")
        if "/" in valor or "\\" in valor or valor.startswith("."):
            raise ValueError("nome de arquivo de foto inválido")
        return valor
