"""Cliente Open-Meteo (sem chave): nebulosidade, visibilidade, nascer e pôr do sol.

Resiliência: timeout, retry com backoff, cache por local/dia e circuit
breaker. Se a API estiver fora, o robô NÃO para: usa horário fixo para saber
se é noite e marca o chamado com `clima_indisponivel = 1`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from ..config import Config
from ..resiliencia import CircuitBreaker, executar_com_retry

log = logging.getLogger("luzsegura.clima")


@dataclass
class Clima:
    nebulosidade_pct: float | None
    visibilidade_m: float | None
    nascer_sol: str | None
    por_do_sol: str | None
    eh_noite: bool
    indisponivel: bool
    fonte: str

    def to_dict(self) -> dict:
        return asdict(self)


class ServicoClima:
    def __init__(self, cfg: Config, sessao: requests.Session | None = None, dormir=time.sleep):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self.dormir = dormir
        self.fuso = ZoneInfo(cfg.fuso)
        self.circuito = CircuitBreaker("open-meteo", cfg.falhas_para_abrir_circuito, reabrir_em_s=300)
        self._cache: dict[tuple, dict] = {}
        self.chamadas_http = 0

    def obter(self, lat: float, lon: float, momento: datetime) -> Clima:
        local = momento.astimezone(self.fuso)
        chave = (round(lat, 2), round(lon, 2), local.date().isoformat())
        dados = self._cache.get(chave)
        if dados is None:
            if not self.circuito.permitir():
                log.warning("Open-Meteo com circuito aberto: usando fallback de horário",
                            extra={"etapa": "enriquecimento"})
                return self._fallback(local)
            try:
                dados = executar_com_retry(
                    lambda: self._buscar(lat, lon, local.date().isoformat()),
                    tentativas=self.cfg.tentativas_http, backoff_base=self.cfg.backoff_base_s,
                    excecoes=(requests.RequestException, ValueError, KeyError),
                    nome="Open-Meteo", dormir=self.dormir)
                self.circuito.sucesso()
                self._cache[chave] = dados
            except (requests.RequestException, ValueError, KeyError) as erro:
                self.circuito.falha()
                log.error("Clima indisponível (%s): relato segue sem fator climático", type(erro).__name__,
                          extra={"etapa": "enriquecimento"})
                return self._fallback(local)
        return self._interpretar(dados, local)

    def _buscar(self, lat: float, lon: float, data: str) -> dict:
        self.chamadas_http += 1
        resp = self.sessao.get(self.cfg.open_meteo_url, timeout=self.cfg.http_timeout_s, params={
            "latitude": round(lat, 4), "longitude": round(lon, 4),
            "hourly": "cloud_cover,visibility", "daily": "sunrise,sunset",
            "timezone": self.cfg.fuso, "start_date": data, "end_date": data,
        })
        resp.raise_for_status()
        dados = resp.json()
        if "hourly" not in dados or "daily" not in dados:
            raise ValueError("resposta da Open-Meteo sem os campos esperados")
        return dados

    def _interpretar(self, dados: dict, local: datetime) -> Clima:
        alvo = local.strftime("%Y-%m-%dT%H:00")
        horas = dados["hourly"].get("time", [])
        neb = vis = None
        if alvo in horas:
            i = horas.index(alvo)
            neb = (dados["hourly"].get("cloud_cover") or [None] * len(horas))[i]
            vis = (dados["hourly"].get("visibility") or [None] * len(horas))[i]
        nascer = (dados["daily"].get("sunrise") or [None])[0]
        por = (dados["daily"].get("sunset") or [None])[0]
        agora_txt = local.strftime("%Y-%m-%dT%H:%M")
        if nascer and por:
            eh_noite = not (nascer <= agora_txt <= por)
        else:
            eh_noite = local.hour >= 18 or local.hour < 6
        return Clima(neb, vis, nascer, por, eh_noite, False, "open-meteo")

    @staticmethod
    def _fallback(local: datetime) -> Clima:
        return Clima(None, None, None, None, local.hour >= 18 or local.hour < 6, True,
                     "fallback_horario_fixo")
