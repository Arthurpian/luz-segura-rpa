"""Funções geográficas: distância, território e pontos de referência."""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

RAIO_TERRA_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos (fórmula de Haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * RAIO_TERRA_M * math.asin(math.sqrt(a))


def deslocar(lat: float, lon: float, norte_m: float, leste_m: float) -> tuple[float, float]:
    """Desloca um ponto N metros ao norte e L metros a leste."""
    dlat = norte_m / 111_320.0
    dlon = leste_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _ponto_no_anel(lat: float, lon: float, anel: list[list[float]]) -> bool:
    dentro = False
    j = len(anel) - 1
    for i in range(len(anel)):
        xi, yi = anel[i][0], anel[i][1]  # GeoJSON: [lon, lat]
        xj, yj = anel[j][0], anel[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
            dentro = not dentro
        j = i
    return dentro


class Territorio:
    """Polígono (GeoJSON) do território atendido pelo piloto."""

    def __init__(self, nome: str, aneis: list[list[list[float]]]):
        self.nome = nome
        self.aneis = aneis

    @classmethod
    def carregar(cls, caminho: Path) -> "Territorio":
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        feicoes = dados["features"] if dados.get("type") == "FeatureCollection" else [dados]
        aneis, nome = [], "territorio"
        for f in feicoes:
            nome = f.get("properties", {}).get("nome", nome)
            geom = f["geometry"]
            if geom["type"] == "Polygon":
                aneis.append(geom["coordinates"][0])
            elif geom["type"] == "MultiPolygon":
                aneis.extend(p[0] for p in geom["coordinates"])
        if not aneis:
            raise ValueError("territorio.geojson não tem polígono válido")
        return cls(nome, aneis)

    def contem(self, lat: float, lon: float) -> bool:
        return any(_ponto_no_anel(lat, lon, anel) for anel in self.aneis)


@dataclass(frozen=True)
class PontoReferencia:
    id: str
    nome: str
    lat: float
    lon: float
    tipo: str            # parada_onibus | estacao | escola | ubs | praca
    fluxo: str | None    # alto | medio | baixo (só para paradas)


def carregar_pontos(caminho: Path) -> tuple[list[PontoReferencia], int]:
    """Lê CSV no padrão GTFS stops.txt (+ colunas tipo e fluxo).

    Retorna (pontos válidos, quantidade de linhas inválidas ignoradas).
    """
    pontos, invalidas = [], 0
    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            try:
                pontos.append(PontoReferencia(
                    id=linha["stop_id"].strip(),
                    nome=linha["stop_name"].strip(),
                    lat=float(linha["stop_lat"]),
                    lon=float(linha["stop_lon"]),
                    tipo=(linha.get("tipo") or "parada_onibus").strip(),
                    fluxo=(linha.get("fluxo") or "").strip() or None,
                ))
            except (KeyError, ValueError, AttributeError):
                invalidas += 1
    return pontos, invalidas


def mais_proximo(lat: float, lon: float, pontos: list[PontoReferencia],
                 tipos: set[str], raio_m: float) -> tuple[PontoReferencia | None, float | None]:
    melhor, melhor_d = None, None
    for p in pontos:
        if p.tipo not in tipos:
            continue
        d = haversine_m(lat, lon, p.lat, p.lon)
        if d <= raio_m and (melhor_d is None or d < melhor_d):
            melhor, melhor_d = p, d
    return melhor, melhor_d
