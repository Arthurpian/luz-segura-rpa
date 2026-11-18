"""Regras de negócio: pontuação de prioridade explicável e SLA.

Cada ponto do score vem de um fator com descrição em português. Isso permite
que o painel e o assistente de IA respondam "por que este ponto está em
primeiro?" citando exatamente os fatores usados pelo robô.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

PESO_FLUXO = {"alto": 1.0, "medio": 0.7, "baixo": 0.4}
SLA_HORAS = {"P1": 24, "P2": 72, "P3": 168, "P4": 360}
FAIXAS = (("P1", 70), ("P2", 50), ("P3", 30), ("P4", 0))
TIPOS_SENSIVEIS = {"escola", "ubs", "estacao", "praca"}
GRAVIDADE = {"adequada": 0, "fraca": 1, "inexistente": 2}

NOMES_PRIORIDADE = {"P1": "crítica", "P2": "alta", "P3": "média", "P4": "baixa"}


def _arredondar(valor: float) -> int:
    return int(valor + 0.5)


@dataclass
class Fator:
    codigo: str
    pontos: int
    descricao: str


@dataclass
class ContextoPrioridade:
    rotulo: str                          # inexistente | fraca
    validacao_ldr: str = "sem_leitura"   # confirmado | contestado | sem_leitura | revisado_humano
    lux_medido: float | None = None
    parada_id: str | None = None
    distancia_parada_m: float | None = None
    fluxo_parada: str | None = None
    pontos_sensiveis: list[str] = field(default_factory=list)
    qtd_relatos: int = 1
    eh_noite: bool = True
    nebulosidade_pct: float | None = None
    visibilidade_m: float | None = None
    reincidente: bool = False
    atrasado: bool = False


@dataclass
class ResultadoPrioridade:
    score: int
    prioridade: str
    sla_horas: int
    fatores: list[Fator]

    @property
    def resumo(self) -> str:
        partes = [f"{f.descricao} (+{f.pontos})" for f in self.fatores]
        nome = NOMES_PRIORIDADE[self.prioridade]
        return f"{self.prioridade} ({nome}), score {self.score}/100: " + "; ".join(partes)

    def motivo_json(self) -> str:
        return json.dumps({"resumo": self.resumo,
                           "fatores": [asdict(f) for f in self.fatores]}, ensure_ascii=False)


def classificar_faixa(score: int) -> str:
    for prioridade, minimo in FAIXAS:
        if score >= minimo:
            return prioridade
    return "P4"  # pragma: no cover


def calcular_prioridade(ctx: ContextoPrioridade) -> ResultadoPrioridade:
    fatores: list[Fator] = []

    # 1. Severidade apontada pela visão computacional
    if ctx.rotulo == "inexistente":
        fatores.append(Fator("severidade", 40, "Foto indica ausência de iluminação"))
    elif ctx.rotulo == "fraca":
        fatores.append(Fator("severidade", 25, "Foto indica iluminação fraca"))

    # 2. Confirmação física pelo sensor LDR (componente Maker Lab)
    if ctx.validacao_ldr == "confirmado":
        lux = f" ({ctx.lux_medido:.1f} lux)" if ctx.lux_medido is not None else ""
        fatores.append(Fator("sensor_ldr", 15, f"Sensor LDR confirmou baixa luminosidade{lux}"))

    # 3. Proximidade de parada de ônibus, ponderada pelo fluxo de pessoas
    if ctx.distancia_parada_m is not None:
        base = 15 if ctx.distancia_parada_m <= 50 else 8 if ctx.distancia_parada_m <= 150 else 0
        pontos = _arredondar(base * PESO_FLUXO.get(ctx.fluxo_parada or "baixo", 0.4))
        if pontos:
            fatores.append(Fator(
                "parada_onibus", pontos,
                f"A {ctx.distancia_parada_m:.0f} m da parada {ctx.parada_id} (fluxo {ctx.fluxo_parada or 'baixo'})"))

    # 4. Pontos sensíveis (escola, UBS, estação, praça)
    if ctx.pontos_sensiveis:
        fatores.append(Fator("ponto_sensivel", 10, "Próximo a " + ", ".join(ctx.pontos_sensiveis)))

    # 5. Recorrência: vários cidadãos relatando o mesmo ponto
    if ctx.qtd_relatos > 1:
        fatores.append(Fator("recorrencia", min(15, 5 * (ctx.qtd_relatos - 1)),
                             f"{ctx.qtd_relatos} relatos para o mesmo ponto"))

    # 6. Clima: noite encoberta ou com baixa visibilidade agrava o risco
    if ctx.eh_noite and (
        (ctx.nebulosidade_pct is not None and ctx.nebulosidade_pct >= 80)
        or (ctx.visibilidade_m is not None and ctx.visibilidade_m < 5000)
    ):
        fatores.append(Fator("clima", 5, "Noite encoberta ou com baixa visibilidade (Open-Meteo)"))

    # 7. Reincidência: poste consertado recentemente voltou a falhar
    if ctx.reincidente:
        fatores.append(Fator("reincidencia", 10, "Ponto consertado nos últimos 30 dias voltou a falhar"))

    # 8. SLA vencido
    if ctx.atrasado:
        fatores.append(Fator("sla_vencido", 10, "Prazo de atendimento (SLA) vencido"))

    score = min(100, sum(f.pontos for f in fatores))
    prioridade = classificar_faixa(score)
    return ResultadoPrioridade(score, prioridade, SLA_HORAS[prioridade], fatores)


def pior_rotulo(a: str, b: str) -> str:
    return a if GRAVIDADE.get(a, 0) >= GRAVIDADE.get(b, 0) else b


def contexto_do_chamado(ch: dict) -> ContextoPrioridade:
    """Reconstrói o contexto a partir de uma linha da tabela `chamados`."""
    return ContextoPrioridade(
        rotulo=ch["rotulo_visao"],
        validacao_ldr=ch["validacao_ldr"] or "sem_leitura",
        lux_medido=ch["lux_medido"],
        parada_id=ch["parada_id"],
        distancia_parada_m=ch["distancia_parada_m"],
        fluxo_parada=ch["fluxo_parada"],
        pontos_sensiveis=json.loads(ch["pontos_sensiveis"] or "[]"),
        qtd_relatos=ch["qtd_relatos"],
        eh_noite=bool(ch["eh_noite"]),
        nebulosidade_pct=ch["nebulosidade_pct"],
        visibilidade_m=ch["visibilidade_m"],
        reincidente=bool(ch["reincidente"]),
        atrasado=bool(ch["atrasado"]),
    )
