"""Configuração central do robô.

Tudo que muda entre ambientes (URLs, chaves, limiares) vem de variáveis de
ambiente ou do arquivo .env. Nenhuma credencial fica no código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

# src/luzsegura_rpa/config.py -> raiz do repositório
RAIZ_PROJETO = Path(__file__).resolve().parents[2]


def _txt(nome: str, padrao: str | None = None) -> str | None:
    valor = os.getenv(nome)
    return valor if valor not in (None, "") else padrao


def _num(nome: str, padrao: float) -> float:
    valor = os.getenv(nome)
    return float(valor) if valor not in (None, "") else padrao


def _int(nome: str, padrao: int) -> int:
    return int(_num(nome, padrao))


@dataclass(frozen=True)
class Config:
    raiz: Path

    # ---- Regras de negócio (todas calibráveis sem mexer no código) ----
    raio_deduplicacao_m: float = 30.0        # relatos a até 30 m viram o mesmo chamado
    raio_ldr_m: float = 40.0                 # leitura do sensor vale para até 40 m
    janela_ldr_horas: int = 72               # leitura do sensor vale por até 72 h
    lux_minimo: float = 15.0                 # acima disso o sensor "contesta" o relato
    limiar_confianca: float = 0.60           # abaixo disso, revisão humana
    raio_parada_m: float = 150.0             # parada de ônibus considerada "próxima"
    raio_ponto_sensivel_m: float = 100.0     # escola, UBS, estação, praça
    janela_reincidencia_dias: int = 30       # poste consertado que volta a falhar
    max_idade_relato_dias: int = 7
    tolerancia_futuro_min: int = 10
    max_foto_mb: float = 5.0
    max_relatos_contato_hora: int = 5        # anti-abuso
    minutos_manuais_por_relato: float = 6.0  # base da estimativa de ganho (AS-IS)

    # ---- Integrações ----
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    http_timeout_s: float = 5.0
    tentativas_http: int = 3
    backoff_base_s: float = 0.5
    falhas_para_abrir_circuito: int = 3
    visao_api_url: str | None = None
    webhook_alerta_url: str | None = None
    telegram_token: str | None = None
    telegram_chat_id: str | None = None

    # ---- Segurança ----
    api_key: str = "troque-esta-chave"
    salt_pseudonimizacao: str = "defina-um-salt-no-env"
    cors_origens: str = "*"
    fuso: str = "America/Sao_Paulo"

    # ---- Pastas (derivadas da raiz) ----
    @property
    def dados(self) -> Path:
        return self.raiz / "data"

    @property
    def inbox(self) -> Path:
        return self.dados / "inbox"

    @property
    def quarentena(self) -> Path:
        return self.dados / "quarentena"

    @property
    def erros(self) -> Path:
        return self.dados / "erros"

    @property
    def processados(self) -> Path:
        return self.dados / "processados"

    @property
    def fotos(self) -> Path:
        return self.dados / "fotos_anonimizadas"

    @property
    def saida(self) -> Path:
        return self.dados / "saida"

    @property
    def referencia(self) -> Path:
        return self.dados / "referencia"

    @property
    def sensores(self) -> Path:
        return self.dados / "sensores"

    @property
    def logs(self) -> Path:
        return self.raiz / "logs"

    @property
    def execucoes(self) -> Path:
        return self.logs / "execucoes"

    @property
    def db_path(self) -> Path:
        return self.dados / "luzsegura.db"

    @property
    def lock_path(self) -> Path:
        return self.dados / ".robo.lock"

    @property
    def territorio_path(self) -> Path:
        return self.referencia / "territorio.geojson"

    @property
    def pontos_path(self) -> Path:
        return self.referencia / "pontos_referencia.csv"

    @property
    def ldr_path(self) -> Path:
        return self.sensores / "leituras_ldr.csv"

    def garantir_pastas(self) -> None:
        for pasta in (self.inbox, self.quarentena, self.erros, self.processados,
                      self.fotos, self.saida, self.referencia, self.sensores,
                      self.logs, self.execucoes):
            pasta.mkdir(parents=True, exist_ok=True)

    @classmethod
    def carregar(cls, raiz: Path | str | None = None, **sobrescritas) -> "Config":
        raiz = Path(raiz or _txt("LUZSEGURA_RAIZ") or RAIZ_PROJETO)
        load_dotenv(raiz / ".env", override=False)
        cfg = cls(
            raiz=raiz,
            raio_deduplicacao_m=_num("RAIO_DEDUPLICACAO_M", 30.0),
            raio_ldr_m=_num("RAIO_LDR_M", 40.0),
            janela_ldr_horas=_int("JANELA_LDR_HORAS", 72),
            lux_minimo=_num("LUX_MINIMO", 15.0),
            limiar_confianca=_num("LIMIAR_CONFIANCA", 0.60),
            raio_parada_m=_num("RAIO_PARADA_M", 150.0),
            raio_ponto_sensivel_m=_num("RAIO_PONTO_SENSIVEL_M", 100.0),
            janela_reincidencia_dias=_int("JANELA_REINCIDENCIA_DIAS", 30),
            max_idade_relato_dias=_int("MAX_IDADE_RELATO_DIAS", 7),
            tolerancia_futuro_min=_int("TOLERANCIA_FUTURO_MIN", 10),
            max_foto_mb=_num("MAX_FOTO_MB", 5.0),
            max_relatos_contato_hora=_int("MAX_RELATOS_CONTATO_HORA", 5),
            minutos_manuais_por_relato=_num("MINUTOS_MANUAIS_POR_RELATO", 6.0),
            open_meteo_url=_txt("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast"),
            http_timeout_s=_num("HTTP_TIMEOUT_S", 5.0),
            tentativas_http=_int("TENTATIVAS_HTTP", 3),
            backoff_base_s=_num("BACKOFF_BASE_S", 0.5),
            falhas_para_abrir_circuito=_int("FALHAS_PARA_ABRIR_CIRCUITO", 3),
            visao_api_url=_txt("VISAO_API_URL"),
            webhook_alerta_url=_txt("WEBHOOK_ALERTA_URL"),
            telegram_token=_txt("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_txt("TELEGRAM_CHAT_ID"),
            api_key=_txt("LUZSEGURA_API_KEY", "troque-esta-chave"),
            salt_pseudonimizacao=_txt("SALT_PSEUDONIMIZACAO", "defina-um-salt-no-env"),
            cors_origens=_txt("CORS_ORIGENS", "*"),
            fuso=_txt("FUSO_HORARIO", "America/Sao_Paulo"),
        )
        return replace(cfg, **sobrescritas) if sobrescritas else cfg
