"""Persistência em SQLite (arquivo data/luzsegura.db).

É o ponto de integração principal com o MVP: a API do produto, o painel e o
pipeline de dados leem as tabelas `chamados`, `relatos`, `fila_revisao`,
`execucoes` e `auditoria`. Todas as escritas de um relato acontecem numa
única transação: ou grava tudo, ou nada.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS chamados (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL,          -- aberto | atrasado | resolvido
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    rotulo_visao        TEXT NOT NULL,
    confianca_visao     REAL,
    validacao_ldr       TEXT,
    lux_medido          REAL,
    parada_id           TEXT,
    parada_nome         TEXT,
    distancia_parada_m  REAL,
    fluxo_parada        TEXT,
    pontos_sensiveis    TEXT,                   -- JSON
    qtd_relatos         INTEGER NOT NULL DEFAULT 1,
    eh_noite            INTEGER,
    nebulosidade_pct    REAL,
    visibilidade_m      REAL,
    clima_indisponivel  INTEGER DEFAULT 0,
    reincidente         INTEGER DEFAULT 0,
    atrasado            INTEGER DEFAULT 0,
    score               INTEGER NOT NULL,
    prioridade          TEXT NOT NULL,
    motivo_prioridade   TEXT NOT NULL,          -- JSON explicável
    criado_em           TEXT NOT NULL,
    atualizado_em       TEXT NOT NULL,
    prazo_sla           TEXT NOT NULL,
    resolvido_em        TEXT,
    run_id_origem       TEXT
);
CREATE INDEX IF NOT EXISTS ix_chamados_status ON chamados(status);

CREATE TABLE IF NOT EXISTS relatos (
    id                   TEXT PRIMARY KEY,
    chamado_id           TEXT REFERENCES chamados(id),
    hash_conteudo        TEXT NOT NULL,
    criado_em            TEXT NOT NULL,
    recebido_em          TEXT NOT NULL,
    latitude             REAL NOT NULL,
    longitude            REAL NOT NULL,
    canal                TEXT,
    contato_hash         TEXT,                  -- pseudonimizado
    descricao_mascarada  TEXT,
    foto_anonimizada     TEXT,
    rotulo_visao         TEXT,
    confianca_visao      REAL,
    fonte_visao          TEXT,
    resultado            TEXT NOT NULL,         -- chamado_criado | mesclado | improcedente | revisao_humana
    motivo               TEXT,
    run_id               TEXT
);
CREATE INDEX IF NOT EXISTS ix_relatos_contato ON relatos(contato_hash);

CREATE TABLE IF NOT EXISTS fila_revisao (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    relato_id    TEXT NOT NULL REFERENCES relatos(id),
    motivo       TEXT NOT NULL,
    detalhe      TEXT,
    status       TEXT NOT NULL DEFAULT 'pendente', -- pendente | aprovado | rejeitado
    criado_em    TEXT NOT NULL,
    decidido_em  TEXT,
    revisor      TEXT,
    observacao   TEXT
);

CREATE TABLE IF NOT EXISTS execucoes (
    run_id        TEXT PRIMARY KEY,
    iniciado_em   TEXT NOT NULL,
    finalizado_em TEXT,
    status        TEXT NOT NULL,
    resumo        TEXT
);

CREATE TABLE IF NOT EXISTS auditoria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT,
    momento     TEXT NOT NULL,
    etapa       TEXT NOT NULL,
    entidade    TEXT NOT NULL,
    entidade_id TEXT,
    acao        TEXT NOT NULL,
    detalhe     TEXT
);
"""

ATIVOS = ("aberto", "atrasado")


class Repositorio:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: a API abre uma conexão por requisição, mas o FastAPI pode
        # fechá-la em outra thread do pool. Cada conexão continua usada por uma requisição só.
        self.con = sqlite3.connect(self.caminho, timeout=10, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(ESQUEMA)
        self._em_transacao = False

    def fechar(self) -> None:
        self.con.close()

    @contextmanager
    def transacao(self):
        self._em_transacao = True
        try:
            with self.con:
                yield self
        finally:
            self._em_transacao = False

    def _commit(self) -> None:
        if not self._em_transacao:
            self.con.commit()

    @staticmethod
    def _dict(linha) -> dict | None:
        return dict(linha) if linha is not None else None

    # ------------------------------------------------------------ relatos
    def relato(self, relato_id: str) -> dict | None:
        return self._dict(self.con.execute("SELECT * FROM relatos WHERE id = ?", (relato_id,)).fetchone())

    def salvar_relato(self, dados: dict) -> None:
        # UPSERT (não usa REPLACE para não violar a FK da fila de revisão no reprocessamento)
        colunas = ", ".join(dados)
        marcas = ", ".join("?" for _ in dados)
        atualiza = ", ".join(f"{c} = excluded.{c}" for c in dados if c != "id")
        self.con.execute(f"INSERT INTO relatos ({colunas}) VALUES ({marcas}) "
                         f"ON CONFLICT(id) DO UPDATE SET {atualiza}", tuple(dados.values()))
        self._commit()

    def relatos_do_contato(self, contato_hash: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, criado_em FROM relatos WHERE contato_hash = ?", (contato_hash,))]

    def relatos_do_chamado(self, chamado_id: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, criado_em, canal, rotulo_visao, confianca_visao, fonte_visao, resultado "
            "FROM relatos WHERE chamado_id = ? ORDER BY criado_em", (chamado_id,))]

    def atualizar_relato(self, relato_id: str, **campos) -> None:
        sets = ", ".join(f"{k} = ?" for k in campos)
        self.con.execute(f"UPDATE relatos SET {sets} WHERE id = ?", (*campos.values(), relato_id))
        self._commit()

    # ----------------------------------------------------------- chamados
    def proximo_id_chamado(self, dia: datetime) -> str:
        prefixo = f"LS-{dia:%Y%m%d}-"
        total = self.con.execute("SELECT COUNT(*) FROM chamados WHERE id LIKE ?", (prefixo + "%",)).fetchone()[0]
        return f"{prefixo}{total + 1:04d}"

    def inserir_chamado(self, dados: dict) -> None:
        colunas = ", ".join(dados)
        marcas = ", ".join("?" for _ in dados)
        self.con.execute(f"INSERT INTO chamados ({colunas}) VALUES ({marcas})", tuple(dados.values()))
        self._commit()

    def atualizar_chamado(self, chamado_id: str, **campos) -> None:
        sets = ", ".join(f"{k} = ?" for k in campos)
        self.con.execute(f"UPDATE chamados SET {sets} WHERE id = ?", (*campos.values(), chamado_id))
        self._commit()

    def chamado(self, chamado_id: str) -> dict | None:
        return self._dict(self.con.execute("SELECT * FROM chamados WHERE id = ?", (chamado_id,)).fetchone())

    def chamados_ativos(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM chamados WHERE status IN (?, ?) ORDER BY criado_em", ATIVOS)]

    def chamados_resolvidos(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM chamados WHERE status = 'resolvido'")]

    def listar_chamados(self, status: str | None = None, prioridade: str | None = None,
                        limite: int | None = None) -> list[dict]:
        sql, args = "SELECT * FROM chamados WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if prioridade:
            sql += " AND prioridade = ?"
            args.append(prioridade)
        sql += " ORDER BY CASE status WHEN 'resolvido' THEN 1 ELSE 0 END, score DESC, criado_em"
        if limite:
            sql += " LIMIT ?"
            args.append(limite)
        return [dict(r) for r in self.con.execute(sql, args)]

    # ------------------------------------------------------ fila_revisao
    def inserir_revisao(self, relato_id: str, motivo: str, detalhe: dict, momento: str) -> int:
        cur = self.con.execute(
            "INSERT INTO fila_revisao (relato_id, motivo, detalhe, criado_em) VALUES (?, ?, ?, ?)",
            (relato_id, motivo, json.dumps(detalhe, ensure_ascii=False), momento))
        self._commit()
        return cur.lastrowid

    def revisao(self, revisao_id: int) -> dict | None:
        return self._dict(self.con.execute("SELECT * FROM fila_revisao WHERE id = ?", (revisao_id,)).fetchone())

    def listar_revisoes(self, status: str = "pendente") -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT f.*, r.latitude, r.longitude, r.rotulo_visao, r.confianca_visao, r.criado_em AS relato_criado_em "
            "FROM fila_revisao f JOIN relatos r ON r.id = f.relato_id WHERE f.status = ? ORDER BY f.criado_em",
            (status,))]

    def decidir_revisao(self, revisao_id: int, status: str, revisor: str, observacao: str | None,
                        momento: str) -> None:
        self.con.execute(
            "UPDATE fila_revisao SET status = ?, revisor = ?, observacao = ?, decidido_em = ? WHERE id = ?",
            (status, revisor, observacao, momento, revisao_id))
        self._commit()

    # ---------------------------------------------------------- execuções
    def iniciar_execucao(self, run_id: str, momento: str) -> None:
        self.con.execute("INSERT INTO execucoes (run_id, iniciado_em, status) VALUES (?, ?, 'em_andamento')",
                         (run_id, momento))
        self._commit()

    def finalizar_execucao(self, run_id: str, momento: str, status: str, resumo: dict) -> None:
        self.con.execute("UPDATE execucoes SET finalizado_em = ?, status = ?, resumo = ? WHERE run_id = ?",
                         (momento, status, json.dumps(resumo, ensure_ascii=False), run_id))
        self._commit()

    def listar_execucoes(self, limite: int = 20) -> list[dict]:
        linhas = self.con.execute("SELECT * FROM execucoes ORDER BY iniciado_em DESC LIMIT ?", (limite,))
        saida = []
        for r in linhas:
            d = dict(r)
            d["resumo"] = json.loads(d["resumo"]) if d["resumo"] else None
            saida.append(d)
        return saida

    # ---------------------------------------------------------- auditoria
    def auditar(self, run_id: str, momento: str, etapa: str, entidade: str, entidade_id: str | None,
                acao: str, detalhe: dict | None = None) -> None:
        self.con.execute(
            "INSERT INTO auditoria (run_id, momento, etapa, entidade, entidade_id, acao, detalhe) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, momento, etapa, entidade, entidade_id, acao,
             json.dumps(detalhe or {}, ensure_ascii=False)))
        self._commit()

    def trilha(self, entidade_id: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT momento, run_id, etapa, acao, detalhe FROM auditoria WHERE entidade_id = ? ORDER BY id",
            (entidade_id,))]

    # -------------------------------------------------------- indicadores
    def indicadores(self, minutos_manuais_por_relato: float) -> dict:
        c = self.con
        por_prioridade = {r[0]: r[1] for r in c.execute(
            "SELECT prioridade, COUNT(*) FROM chamados WHERE status IN ('aberto','atrasado') GROUP BY prioridade")}
        por_status = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM chamados GROUP BY status")}
        por_resultado = {r[0]: r[1] for r in c.execute("SELECT resultado, COUNT(*) FROM relatos GROUP BY resultado")}
        total_relatos = sum(por_resultado.values())
        resolvidos = c.execute(
            "SELECT criado_em, resolvido_em FROM chamados WHERE status = 'resolvido' AND resolvido_em IS NOT NULL"
        ).fetchall()
        horas = [(datetime.fromisoformat(r[1]) - datetime.fromisoformat(r[0])).total_seconds() / 3600
                 for r in resolvidos]
        pendentes = c.execute("SELECT COUNT(*) FROM fila_revisao WHERE status = 'pendente'").fetchone()[0]
        return {
            "chamados_ativos_por_prioridade": por_prioridade,
            "chamados_por_status": por_status,
            "relatos_por_resultado": por_resultado,
            "total_relatos": total_relatos,
            "taxa_mesclados_pct": round(100 * por_resultado.get("mesclado", 0) / total_relatos, 1) if total_relatos else 0,
            "taxa_revisao_humana_pct": round(100 * por_resultado.get("revisao_humana", 0) / total_relatos, 1) if total_relatos else 0,
            "revisoes_pendentes": pendentes,
            "tempo_medio_ate_conserto_h": round(sum(horas) / len(horas), 1) if horas else None,
            "horas_manuais_economizadas": round(total_relatos * minutos_manuais_por_relato / 60, 1),
        }
