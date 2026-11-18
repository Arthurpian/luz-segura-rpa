"""Classificação da iluminação na foto.

Ordem de preferência:
1. Classificação que já veio no relato (o app chamou o modelo de Visão Computacional).
2. API do componente de Visão (VISAO_API_URL), com retry e circuit breaker.
3. Fallback local por luminância média (Pillow). Não substitui o modelo
   treinado; existe para o processo não parar se a visão estiver fora.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests
from PIL import Image, ImageStat
from pydantic import ValidationError

from ..config import Config
from ..modelos import ClassificacaoVisao
from ..resiliencia import CircuitBreaker, executar_com_retry

log = logging.getLogger("luzsegura.visao")

LIMIAR_ESCURO = 35   # luminância média (0-255) abaixo disso: inexistente
LIMIAR_FRACO = 80    # abaixo disso: fraca; acima: adequada


class ServicoVisao:
    def __init__(self, cfg: Config, sessao: requests.Session | None = None, dormir=time.sleep):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self.dormir = dormir
        self.circuito = CircuitBreaker("visao-api", cfg.falhas_para_abrir_circuito, reabrir_em_s=300)

    def classificar(self, foto: Path, informada: ClassificacaoVisao | None) -> tuple[ClassificacaoVisao, bool]:
        """Retorna (classificação, degradada?)."""
        if informada is not None:
            return informada, False
        if self.cfg.visao_api_url:
            if self.circuito.permitir():
                try:
                    resultado = executar_com_retry(
                        lambda: self._chamar_api(foto), tentativas=self.cfg.tentativas_http,
                        backoff_base=self.cfg.backoff_base_s,
                        excecoes=(requests.RequestException, ValueError, ValidationError),
                        nome="API de Visão", dormir=self.dormir)
                    self.circuito.sucesso()
                    return resultado, False
                except (requests.RequestException, ValueError, ValidationError):
                    self.circuito.falha()
            log.warning("API de Visão indisponível: usando heurística de luminância",
                        extra={"etapa": "visao"})
            return self.heuristica(foto), True
        return self.heuristica(foto), False

    def _chamar_api(self, foto: Path) -> ClassificacaoVisao:
        with foto.open("rb") as f:
            resp = self.sessao.post(self.cfg.visao_api_url, files={"foto": (foto.name, f, "image/jpeg")},
                                    timeout=self.cfg.http_timeout_s)
        resp.raise_for_status()
        dados = resp.json()
        return ClassificacaoVisao(rotulo=dados["rotulo"], confianca=float(dados["confianca"]),
                                  fonte="api_visao")

    @staticmethod
    def heuristica(foto: Path) -> ClassificacaoVisao:
        with Image.open(foto) as img:
            cinza = img.convert("L")
            cinza.thumbnail((256, 256))
            media = ImageStat.Stat(cinza).mean[0]
        if media < LIMIAR_ESCURO:
            rotulo = "inexistente"
        elif media < LIMIAR_FRACO:
            rotulo = "fraca"
        else:
            rotulo = "adequada"
        # Quanto mais longe do limiar, mais confiança. Perto do limiar -> revisão humana.
        distancia = min(abs(media - LIMIAR_ESCURO), abs(media - LIMIAR_FRACO))
        confianca = round(max(0.50, min(0.95, 0.50 + distancia / 60)), 2)
        return ClassificacaoVisao(rotulo=rotulo, confianca=confianca, fonte="heuristica_luminancia")
