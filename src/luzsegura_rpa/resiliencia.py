"""Retry com backoff exponencial, circuit breaker e trava de execução."""
from __future__ import annotations

import logging
import os
import random
import time
from typing import Callable, TypeVar
from urllib.parse import urlparse

log = logging.getLogger("luzsegura.resiliencia")
T = TypeVar("T")


def resumir_erro(erro: BaseException) -> str:
    """Mensagem curta para log: tipo do erro + host (sem URL completa nem parâmetros)."""
    requisicao = getattr(erro, "request", None)
    url = getattr(requisicao, "url", None)
    if url:
        return f"{type(erro).__name__} em {urlparse(url).netloc}"
    texto = str(erro)
    return f"{type(erro).__name__}: {texto[:120]}{'...' if len(texto) > 120 else ''}"


def executar_com_retry(
    funcao: Callable[[], T],
    *,
    tentativas: int,
    backoff_base: float,
    excecoes: tuple[type[BaseException], ...] = (Exception,),
    nome: str = "operacao",
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Executa `funcao` até `tentativas` vezes (espera 0,5 s, 1 s, 2 s... + jitter)."""
    for tentativa in range(1, tentativas + 1):
        try:
            return funcao()
        except excecoes as erro:
            if tentativa == tentativas:
                log.error("%s falhou após %d tentativa(s): %s", nome, tentativas, resumir_erro(erro),
                          extra={"etapa": "retry", "tentativa": tentativa})
                raise
            espera = backoff_base * (2 ** (tentativa - 1)) + random.uniform(0, backoff_base / 2)
            log.warning("%s falhou (tentativa %d/%d): %s. Nova tentativa em %.2fs",
                        nome, tentativa, tentativas, resumir_erro(erro), espera,
                        extra={"etapa": "retry", "tentativa": tentativa})
            dormir(espera)
    raise RuntimeError("inalcançável")  # pragma: no cover


class CircuitBreaker:
    """Depois de N falhas seguidas, para de chamar o serviço por um tempo.

    Evita que uma API fora do ar deixe o lote inteiro lento (cada relato
    esperaria todos os timeouts). Enquanto aberto, o robô usa o fallback.
    """

    def __init__(self, nome: str, limite_falhas: int = 3, reabrir_em_s: float = 300,
                 relogio: Callable[[], float] = time.monotonic):
        self.nome = nome
        self.limite_falhas = limite_falhas
        self.reabrir_em_s = reabrir_em_s
        self._relogio = relogio
        self.falhas_seguidas = 0
        self._aberto_desde: float | None = None

    @property
    def estado(self) -> str:
        if self._aberto_desde is None:
            return "fechado"
        if self._relogio() - self._aberto_desde >= self.reabrir_em_s:
            return "meio_aberto"
        return "aberto"

    def permitir(self) -> bool:
        return self.estado != "aberto"

    def sucesso(self) -> None:
        if self._aberto_desde is not None:
            log.info("Circuito %s fechado novamente (serviço respondeu)", self.nome)
        self.falhas_seguidas = 0
        self._aberto_desde = None

    def falha(self) -> None:
        self.falhas_seguidas += 1
        if self.falhas_seguidas >= self.limite_falhas and self._aberto_desde is None:
            self._aberto_desde = self._relogio()
            log.error("Circuito %s ABERTO após %d falhas seguidas: usando fallback",
                      self.nome, self.falhas_seguidas, extra={"etapa": "circuit_breaker"})
        elif self.estado == "meio_aberto":
            self._aberto_desde = self._relogio()


class ExecucaoConcorrente(RuntimeError):
    pass


class TravaExecucao:
    """Impede duas execuções do robô ao mesmo tempo (agendador + execução manual)."""

    def __init__(self, caminho, validade_s: float = 1800):
        self.caminho = caminho
        self.validade_s = validade_s

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(f"pid={os.getpid()} inicio={time.time():.0f}")
                return self
            except FileExistsError:
                idade = time.time() - os.path.getmtime(self.caminho)
                if idade < self.validade_s:
                    raise ExecucaoConcorrente(
                        f"Outra execução está em andamento (trava criada há {idade:.0f}s)")
                log.warning("Trava antiga (%.0fs) encontrada e removida", idade)
                os.remove(self.caminho)
        raise ExecucaoConcorrente("Não foi possível obter a trava de execução")

    def __exit__(self, *exc):
        try:
            os.remove(self.caminho)
        except FileNotFoundError:
            pass
        return False
