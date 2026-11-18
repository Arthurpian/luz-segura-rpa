"""API REST de integração com o MVP (FastAPI).

Leitura (pública, sem dados pessoais):
    GET  /health                      saúde do robô e última execução
    GET  /chamados                    lista priorizada (filtros: status, prioridade)
    GET  /chamados/{id}               detalhe + fatores da prioridade + relatos + trilha de auditoria
    GET  /indicadores                 KPIs de impacto e operação
    GET  /execucoes                   histórico de execuções do robô
    GET  /revisao                     fila de revisão humana (pendentes)
    GET  /referencias                 território e pontos de referência (para o mapa)

Escrita (exige header X-API-Key):
    POST  /relatos                    app do cidadão envia relato (foto em base64)
    POST  /revisao/{id}/decisao       revisor aprova (reenfileira) ou rejeita
    PATCH /chamados/{id}/status       equipe de manutenção marca como resolvido
    POST  /robo/executar              dispara uma execução (demonstração)

Documentação interativa em /docs.
"""
from __future__ import annotations

import base64
import binascii
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .banco import Repositorio
from .config import Config
from .exportacao import chamado_publico
from .geo import carregar_pontos
from .modelos import RelatoEntrada, Rotulo
from .resiliencia import ExecucaoConcorrente

ESTATICO = Path(__file__).parent / "static"


class RelatoApi(RelatoEntrada):
    foto: str = Field(default="", description="preenchido pela API")
    foto_base64: str = Field(min_length=20, description="JPEG ou PNG em base64")


class DecisaoRevisao(BaseModel):
    decisao: Literal["aprovar", "rejeitar"]
    rotulo: Rotulo | None = Field(default=None, description="obrigatório ao aprovar: o que o revisor viu na foto")
    revisor: str = Field(min_length=2, max_length=60)
    observacao: str | None = Field(default=None, max_length=300)


class MudancaStatus(BaseModel):
    status: Literal["resolvido"]
    responsavel: str = Field(min_length=2, max_length=60)


def criar_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.carregar()
    cfg.garantir_pastas()
    fuso = ZoneInfo(cfg.fuso)
    app = FastAPI(title="Luz Segura — API do Robô RPA", version="1.0.0",
                  description="Integração entre o robô de triagem de relatos e o MVP Luz Segura.")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in cfg.cors_origens.split(",")],
                       allow_methods=["*"], allow_headers=["*"])

    def repo():
        r = Repositorio(cfg.db_path)
        try:
            yield r
        finally:
            r.fechar()

    def exigir_chave(x_api_key: str | None = Header(default=None)):
        if x_api_key != cfg.api_key:
            raise HTTPException(401, "X-API-Key ausente ou inválida")

    def agora() -> str:
        return datetime.now(fuso).isoformat(timespec="seconds")

    app.mount("/static", StaticFiles(directory=ESTATICO), name="static")

    @app.get("/", include_in_schema=False)
    def painel():
        return FileResponse(ESTATICO / "painel.html")

    @app.get("/referencias")
    def referencias():
        territorio = json.loads(cfg.territorio_path.read_text(encoding="utf-8")) if cfg.territorio_path.exists() else None
        pontos = carregar_pontos(cfg.pontos_path)[0] if cfg.pontos_path.exists() else []
        return {"territorio": territorio, "pontos": [p.__dict__ for p in pontos]}

    @app.get("/health")
    def health(r: Repositorio = Depends(repo)):
        ultima = r.listar_execucoes(1)
        return {"status": "ok", "banco": cfg.db_path.name, "ultima_execucao": ultima[0] if ultima else None}

    @app.get("/chamados")
    def listar(status: str | None = None, prioridade: str | None = Query(default=None, pattern="^P[1-4]$"),
               limite: int = Query(default=200, ge=1, le=1000), r: Repositorio = Depends(repo)):
        return [chamado_publico(c) for c in r.listar_chamados(status, prioridade, limite)]

    @app.get("/chamados/{chamado_id}")
    def detalhe(chamado_id: str, r: Repositorio = Depends(repo)):
        ch = r.chamado(chamado_id)
        if not ch:
            raise HTTPException(404, "chamado não encontrado")
        trilha = r.trilha(chamado_id)
        for e in trilha:
            e["detalhe"] = json.loads(e["detalhe"] or "{}")
        return {**chamado_publico(ch), "relatos": r.relatos_do_chamado(chamado_id), "auditoria": trilha}

    @app.patch("/chamados/{chamado_id}/status", dependencies=[Depends(exigir_chave)])
    def mudar_status(chamado_id: str, corpo: MudancaStatus, r: Repositorio = Depends(repo)):
        ch = r.chamado(chamado_id)
        if not ch:
            raise HTTPException(404, "chamado não encontrado")
        if ch["status"] == "resolvido":
            raise HTTPException(409, "chamado já resolvido")
        momento = agora()
        r.atualizar_chamado(chamado_id, status="resolvido", resolvido_em=momento, atualizado_em=momento)
        r.auditar("api", momento, "manutencao", "chamado", chamado_id, "resolvido", {"responsavel": corpo.responsavel})
        return chamado_publico(r.chamado(chamado_id))

    @app.get("/indicadores")
    def indicadores(r: Repositorio = Depends(repo)):
        return r.indicadores(cfg.minutos_manuais_por_relato)

    @app.get("/execucoes")
    def execucoes(limite: int = Query(default=20, ge=1, le=200), r: Repositorio = Depends(repo)):
        return r.listar_execucoes(limite)

    @app.get("/revisao")
    def fila_revisao(r: Repositorio = Depends(repo)):
        fila = r.listar_revisoes("pendente")
        for item in fila:
            item["detalhe"] = json.loads(item["detalhe"] or "{}")
        return fila

    @app.post("/revisao/{revisao_id}/decisao", dependencies=[Depends(exigir_chave)])
    def decidir(revisao_id: int, corpo: DecisaoRevisao, r: Repositorio = Depends(repo)):
        item = r.revisao(revisao_id)
        if not item:
            raise HTTPException(404, "item de revisão não encontrado")
        if item["status"] != "pendente":
            raise HTTPException(409, f"item já decidido ({item['status']})")
        relato = r.relato(item["relato_id"])
        momento = agora()
        if corpo.decisao == "rejeitar":
            r.decidir_revisao(revisao_id, "rejeitado", corpo.revisor, corpo.observacao, momento)
            r.atualizar_relato(relato["id"], resultado="improcedente", motivo="rejeitado na revisão humana")
            r.auditar("api", momento, "revisao", "relato", relato["id"], "rejeitado", {"revisor": corpo.revisor})
            return {"revisao_id": revisao_id, "status": "rejeitado"}

        if not corpo.rotulo:
            raise HTTPException(422, "informe o rótulo ao aprovar")
        # Reenfileira o relato com a classificação do revisor: o robô cria o chamado na próxima execução
        foto = cfg.fotos / relato["foto_anonimizada"]
        shutil.copy(foto, cfg.inbox / f"{relato['id']}.jpg")
        reenvio = {
            "id": relato["id"], "criado_em": relato["criado_em"], "latitude": relato["latitude"],
            "longitude": relato["longitude"], "foto": f"{relato['id']}.jpg", "canal": relato["canal"],
            "descricao": relato["descricao_mascarada"],
            "classificacao_visao": {"rotulo": corpo.rotulo, "confianca": 1.0, "fonte": "revisor_humano"},
        }
        (cfg.inbox / f"revisado_{relato['id']}.json").write_text(json.dumps(reenvio, ensure_ascii=False, indent=2),
                                                                 encoding="utf-8")
        r.decidir_revisao(revisao_id, "aprovado", corpo.revisor, corpo.observacao, momento)
        r.auditar("api", momento, "revisao", "relato", relato["id"], "aprovado_reenfileirado",
                  {"revisor": corpo.revisor, "rotulo": corpo.rotulo})
        return {"revisao_id": revisao_id, "status": "aprovado", "reenfileirado": True}

    @app.post("/relatos", status_code=202, dependencies=[Depends(exigir_chave)])
    def receber_relato(corpo: RelatoApi):
        try:
            conteudo = base64.b64decode(corpo.foto_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "foto_base64 inválida")
        if len(conteudo) > cfg.max_foto_mb * 1024 * 1024:
            raise HTTPException(413, f"foto acima de {cfg.max_foto_mb} MB")
        extensao = ".png" if conteudo[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
        nome_foto = f"{corpo.id}{extensao}"
        destino = cfg.inbox / f"api_{corpo.id}.json"
        if destino.exists():
            raise HTTPException(409, "relato já está na fila")
        (cfg.inbox / nome_foto).write_bytes(conteudo)
        dados = corpo.model_dump(mode="json", exclude={"foto_base64"})
        dados["foto"] = nome_foto
        destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": corpo.id, "status": "na_fila", "mensagem": "Relato recebido. Obrigado por ajudar a iluminar a cidade."}

    @app.post("/robo/executar", dependencies=[Depends(exigir_chave)])
    def executar():
        from .robo import Robo
        try:
            return Robo(cfg).executar().to_dict()
        except ExecucaoConcorrente as erro:
            raise HTTPException(409, str(erro))

    return app
