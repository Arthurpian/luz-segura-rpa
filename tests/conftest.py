"""Fixtures compartilhadas: ambiente isolado em pasta temporária, relógio fixo e Open-Meteo simulada."""
from __future__ import annotations

import csv
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from luzsegura_rpa.config import Config  # noqa: E402
from luzsegura_rpa.dados_simulados import _p, gerar_foto, gerar_referencias  # noqa: E402
from luzsegura_rpa.logs import configurar_logs  # noqa: E402
from luzsegura_rpa.robo import Robo  # noqa: E402
from luzsegura_rpa.servicos.clima import ServicoClima  # noqa: E402

FUSO = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 11, 18, 10, 0, tzinfo=FUSO)
NOITE = datetime(2026, 11, 17, 21, 0, tzinfo=FUSO)


class RespostaFalsa:
    def __init__(self, dados: dict, status: int = 200):
        self._dados, self.status_code = dados, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._dados


class OpenMeteoFalsa:
    """Simula a API Open-Meteo. modo: ok | offline | resposta_estranha."""

    def __init__(self, modo: str = "ok", nebulosidade: float = 90, visibilidade: float = 3000):
        self.modo, self.nebulosidade, self.visibilidade = modo, nebulosidade, visibilidade
        self.chamadas = 0

    def get(self, url, params=None, timeout=None):
        self.chamadas += 1
        if self.modo == "offline":
            raise requests.ConnectionError("sem rede (simulado)")
        if self.modo == "resposta_estranha":
            return RespostaFalsa({"erro": "formato inesperado"})
        data = params["start_date"]
        return RespostaFalsa({
            "hourly": {"time": [f"{data}T{h:02d}:00" for h in range(24)],
                       "cloud_cover": [self.nebulosidade] * 24, "visibility": [self.visibilidade] * 24},
            "daily": {"sunrise": [f"{data}T05:10"], "sunset": [f"{data}T18:45"]},
        })


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config.carregar(raiz=tmp_path, backoff_base_s=0.0, salt_pseudonimizacao="salt-de-teste",
                        api_key="chave-teste", visao_api_url=None, webhook_alerta_url=None,
                        telegram_token=None, telegram_chat_id=None)
    c.garantir_pastas()
    gerar_referencias(c)
    return c


def fazer_robo(cfg: Config, clima_api: OpenMeteoFalsa | None = None, agora: datetime = AGORA, **kw) -> Robo:
    configurar_logs(cfg, console=False)
    clima = ServicoClima(cfg, sessao=clima_api or OpenMeteoFalsa(), dormir=lambda _s: None)
    return Robo(cfg, clima=clima, relogio=lambda: agora, **kw)


def escrever_relato(cfg: Config, nome: str, norte: float, leste: float, *, luminancia: float = 8,
                    minutos: int = 0, rotulo: str | None = "inexistente", confianca: float = 0.92,
                    **campos) -> dict:
    """Grava um relato + foto na caixa de entrada, como o app faria."""
    rid = campos.pop("id", str(uuid.uuid4()))
    momento = campos.pop("criado_em", NOITE + timedelta(minutes=minutos))
    foto = campos.pop("foto", f"{rid}.jpg")
    if campos.pop("gerar_foto", True):
        gerar_foto(cfg.inbox / foto, luminancia, abs(hash(rid)) % 1000)
    lat, lon = _p(norte, leste)
    dados = {"id": rid, "criado_em": momento.isoformat() if isinstance(momento, datetime) else momento,
             "latitude": lat, "longitude": lon, "foto": foto, "canal": "app", **campos}
    if rotulo:
        dados["classificacao_visao"] = {"rotulo": rotulo, "confianca": confianca, "fonte": "app_visao"}
    (cfg.inbox / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados


def escrever_ldr(cfg: Config, leituras: list[tuple]) -> None:
    """leituras: (norte, leste, lux, momento)."""
    with cfg.ldr_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dispositivo", "lido_em", "latitude", "longitude", "lux"])
        for norte, leste, lux, momento in leituras:
            w.writerow(["LDR-T", momento.isoformat() if isinstance(momento, datetime) else momento,
                        *_p(norte, leste), lux])


def ler_jsonl(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
