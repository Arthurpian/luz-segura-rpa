"""Logs estruturados (JSON Lines) com mascaramento LGPD.

Cada linha do arquivo logs/luzsegura_robo.jsonl tem data/hora, nível,
run_id, etapa, item processado e resultado. Dados pessoais são mascarados
antes de chegar a qualquer handler.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from .config import Config
from .lgpd import mascarar_texto

run_id_atual: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")

CAMPOS_EXTRA = ("etapa", "relato_id", "chamado_id", "resultado", "motivo",
                "arquivo", "tentativa", "prioridade", "score")


class FiltroLGPD(logging.Filter):
    """Mascara e-mail, telefone, CPF e placa na mensagem e injeta o run_id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mascarar_texto(record.getMessage())
        record.args = ()
        if not hasattr(record, "run_id"):
            record.run_id = run_id_atual.get()
        return True


class FormatadorJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        linha = {
            "momento": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "run_id": getattr(record, "run_id", "-"),
            "componente": record.name,
            "mensagem": record.getMessage(),
        }
        for campo in CAMPOS_EXTRA:
            if hasattr(record, campo):
                linha[campo] = getattr(record, campo)
        if record.exc_info:
            tipo = record.exc_info[0].__name__ if record.exc_info[0] else "Erro"
            linha["erro"] = {"tipo": tipo,
                             "detalhe": mascarar_texto(str(record.exc_info[1]))[:500]}
        return json.dumps(linha, ensure_ascii=False)


class FormatadorConsole(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        hora = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        etapa = getattr(record, "etapa", "")
        etapa = f"[{etapa}] " if etapa else ""
        return f"{hora} | {record.levelname:<8} | {etapa}{record.getMessage()}"


def configurar_logs(cfg: Config, nivel: str = "INFO", console: bool = True) -> logging.Logger:
    cfg.logs.mkdir(parents=True, exist_ok=True)
    raiz = logging.getLogger("luzsegura")
    raiz.setLevel(nivel)
    raiz.propagate = False
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()

    arquivo = RotatingFileHandler(cfg.logs / "luzsegura_robo.jsonl", maxBytes=5_000_000,
                                  backupCount=5, encoding="utf-8")
    arquivo.setFormatter(FormatadorJSON())
    arquivo.addFilter(FiltroLGPD())
    raiz.addHandler(arquivo)

    if console:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows
        except (AttributeError, ValueError):
            pass
        tela = logging.StreamHandler(sys.stdout)
        tela.setFormatter(FormatadorConsole())
        tela.addFilter(FiltroLGPD())
        raiz.addHandler(tela)
    return raiz


def fechar_logs() -> None:
    """Fecha os arquivos de log (necessário no Windows antes de apagá-los)."""
    raiz = logging.getLogger("luzsegura")
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()
