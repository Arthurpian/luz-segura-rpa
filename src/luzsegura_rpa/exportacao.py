"""Exportação dos chamados em arquivos estruturados para o MVP.

- data/saida/chamados.json     -> lista para o app, o painel e o assistente RAG
- data/saida/chamados.geojson  -> camada pronta para mapas (Leaflet, QGIS, Power BI)

A escrita é atômica (arquivo temporário + replace): quem estiver lendo nunca
pega um arquivo pela metade.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .banco import Repositorio
from .config import Config

CAMPOS_PUBLICOS = (
    "id", "status", "latitude", "longitude", "rotulo_visao", "confianca_visao", "validacao_ldr",
    "lux_medido", "parada_id", "parada_nome", "distancia_parada_m", "fluxo_parada", "qtd_relatos",
    "clima_indisponivel", "reincidente", "atrasado", "score", "prioridade", "criado_em",
    "atualizado_em", "prazo_sla", "resolvido_em",
)


def chamado_publico(ch: dict) -> dict:
    """Formato de saída do contrato de integração (sem dados pessoais)."""
    saida = {c: ch.get(c) for c in CAMPOS_PUBLICOS}
    saida["pontos_sensiveis"] = json.loads(ch.get("pontos_sensiveis") or "[]")
    motivo = json.loads(ch.get("motivo_prioridade") or "{}")
    saida["motivo_prioridade"] = motivo.get("resumo")
    saida["fatores_prioridade"] = motivo.get("fatores", [])
    for flag in ("clima_indisponivel", "reincidente", "atrasado"):
        saida[flag] = bool(saida[flag])
    return saida


def _gravar_atomico(caminho: Path, conteudo: dict) -> None:
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def exportar_chamados(repo: Repositorio, cfg: Config, run_id: str, momento: datetime) -> int:
    cfg.saida.mkdir(parents=True, exist_ok=True)
    chamados = [chamado_publico(c) for c in repo.listar_chamados()]
    cabecalho = {"gerado_em": momento.isoformat(timespec="seconds"), "run_id": run_id,
                 "versao_contrato": "1.0", "total": len(chamados)}
    _gravar_atomico(cfg.saida / "chamados.json", {**cabecalho, "chamados": chamados})
    _gravar_atomico(cfg.saida / "chamados.geojson", {
        "type": "FeatureCollection",
        "metadata": cabecalho,
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c["longitude"], c["latitude"]]},
            "properties": {k: v for k, v in c.items() if k not in ("latitude", "longitude")},
        } for c in chamados],
    })
    return len(chamados)
