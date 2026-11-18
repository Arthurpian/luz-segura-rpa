"""Leituras do sensor LDR (componente Maker Lab) e validação física do relato."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..geo import haversine_m


@dataclass(frozen=True)
class LeituraLDR:
    dispositivo: str
    lido_em: datetime
    lat: float
    lon: float
    lux: float


def carregar_leituras(caminho: Path, fuso: str) -> tuple[list[LeituraLDR], int]:
    """Lê o CSV exportado pela estação LDR. Linhas inválidas são contadas, não derrubam o lote."""
    if not caminho.exists():
        return [], 0
    tz = ZoneInfo(fuso)
    leituras, invalidas = [], 0
    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            try:
                momento = datetime.fromisoformat(linha["lido_em"].strip())
                if momento.tzinfo is None:
                    momento = momento.replace(tzinfo=tz)
                lux = float(linha["lux"])
                if lux < 0:
                    raise ValueError("lux negativo")
                leituras.append(LeituraLDR(linha["dispositivo"].strip(), momento,
                                           float(linha["latitude"]), float(linha["longitude"]), lux))
            except (KeyError, ValueError, AttributeError):
                invalidas += 1
    return leituras, invalidas


def _noturna(momento: datetime) -> bool:
    return momento.hour >= 18 or momento.hour < 6


def validar_com_ldr(lat: float, lon: float, momento: datetime, leituras: list[LeituraLDR],
                    raio_m: float, janela_h: int, lux_minimo: float):
    """Retorna (status, leitura, distância). status: confirmado | contestado | sem_leitura."""
    janela = timedelta(hours=janela_h)
    candidatas = []
    for leitura in leituras:
        if not _noturna(leitura.lido_em.astimezone(momento.tzinfo)):
            continue
        if abs(leitura.lido_em - momento) > janela:
            continue
        d = haversine_m(lat, lon, leitura.lat, leitura.lon)
        if d <= raio_m:
            candidatas.append((d, abs(leitura.lido_em - momento), leitura))
    if not candidatas:
        return "sem_leitura", None, None
    d, _, leitura = min(candidatas, key=lambda c: (c[0], c[1]))
    status = "confirmado" if leitura.lux < lux_minimo else "contestado"
    return status, leitura, d
