"""CENÁRIOS DE DECISÃO: cada gateway do BPMN tem pelo menos um teste."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import AGORA, NOITE, OpenMeteoFalsa, escrever_ldr, escrever_relato, fazer_robo, ler_jsonl
from luzsegura_rpa.api import criar_app
from luzsegura_rpa.banco import Repositorio
from luzsegura_rpa.dados_simulados import _chamado_historico, _p
from luzsegura_rpa.regras import ContextoPrioridade, calcular_prioridade

pytestmark = pytest.mark.decisao


# ---------------------------------------------------------------- regras puras
@pytest.mark.parametrize("ctx, score, prioridade", [
    (ContextoPrioridade(rotulo="inexistente", validacao_ldr="confirmado", distancia_parada_m=20,
                        fluxo_parada="alto", parada_id="P"), 70, "P1"),
    (ContextoPrioridade(rotulo="fraca", validacao_ldr="confirmado", distancia_parada_m=18,
                        fluxo_parada="medio", parada_id="P", pontos_sensiveis=["Escola"]), 61, "P2"),
    (ContextoPrioridade(rotulo="inexistente", distancia_parada_m=120, fluxo_parada="baixo", parada_id="P"), 43, "P3"),
    (ContextoPrioridade(rotulo="fraca"), 25, "P4"),
    (ContextoPrioridade(rotulo="fraca", qtd_relatos=9), 40, "P3"),           # recorrência limitada a +15
    (ContextoPrioridade(rotulo="inexistente", validacao_ldr="confirmado", distancia_parada_m=10, fluxo_parada="alto",
                        parada_id="P", pontos_sensiveis=["UBS"], qtd_relatos=4, nebulosidade_pct=95,
                        reincidente=True, atrasado=True), 100, "P1"),       # teto de 100
    (ContextoPrioridade(rotulo="inexistente", eh_noite=False, nebulosidade_pct=100), 40, "P3"),  # clima só conta à noite
])
def test_tabela_de_prioridade(ctx, score, prioridade):
    res = calcular_prioridade(ctx)
    assert (res.score, res.prioridade) == (score, prioridade)
    assert res.resumo.startswith(prioridade)


# ------------------------------------------------------ deduplicação geográfica
def test_relatos_a_menos_de_30m_sao_mesclados(cfg):
    escrever_relato(cfg, "a", 15, 13)
    escrever_relato(cfg, "b", 22, 20, minutos=10)   # ~10 m
    resumo = fazer_robo(cfg).executar()
    assert resumo.chamados_criados == 1 and resumo.mesclados == 1
    ch = fazer_robo(cfg).repo.listar_chamados()[0]
    assert ch["qtd_relatos"] == 2


def test_relatos_a_mais_de_30m_geram_chamados_diferentes(cfg):
    escrever_relato(cfg, "a", 15, 13)
    escrever_relato(cfg, "b", 75, 13, minutos=10)   # ~60 m
    resumo = fazer_robo(cfg).executar()
    assert resumo.chamados_criados == 2 and resumo.mesclados == 0


def test_recorrencia_eleva_p2_para_p1_e_dispara_alerta(cfg):
    escrever_ldr(cfg, [(15, 13, 5.0, NOITE)])
    for i in range(4):  # fraca(25) + LDR(15) + parada alto(15) = 55 -> com 4 relatos +15 = 70
        escrever_relato(cfg, f"r{i}", 15 + i, 13, rotulo="fraca", minutos=i)
    resumo = fazer_robo(cfg, OpenMeteoFalsa(nebulosidade=10, visibilidade=20000)).executar()
    assert resumo.chamados_criados == 1 and resumo.mesclados == 3
    alertas = ler_jsonl(cfg.saida / "alertas.jsonl")
    assert [a["tipo"] for a in alertas] == ["p1_por_recorrencia"]


# --------------------------------------------------------- confiança e iluminação
def test_baixa_confianca_vai_para_revisao_humana(cfg):
    escrever_relato(cfg, "a", 200, -400, rotulo="inexistente", confianca=0.41)
    robo = fazer_robo(cfg)
    resumo = robo.executar()
    assert resumo.revisao_humana == 1 and resumo.chamados_criados == 0
    assert robo.repo.listar_revisoes()[0]["motivo"] == "baixa_confianca_visao"


def test_sem_classificacao_do_app_usa_heuristica(cfg):
    escrever_relato(cfg, "a", 200, -400, rotulo=None, luminancia=9)
    robo = fazer_robo(cfg)
    robo.executar()
    relato = robo.repo.con.execute("SELECT fonte_visao, rotulo_visao FROM relatos").fetchone()
    assert tuple(relato) == ("heuristica_luminancia", "inexistente")


def test_iluminacao_adequada_e_improcedente(cfg):
    escrever_relato(cfg, "a", -300, 300, rotulo="adequada", confianca=0.93, luminancia=170)
    resumo = fazer_robo(cfg).executar()
    assert resumo.improcedentes == 1 and resumo.chamados_criados == 0


# ------------------------------------------------------------------ sensor LDR
def test_sensor_contesta_relato_e_envia_para_revisao(cfg):
    escrever_ldr(cfg, [(-498, 405, 42.0, NOITE - timedelta(minutes=30))])
    escrever_relato(cfg, "a", -500, 400)
    robo = fazer_robo(cfg)
    resumo = robo.executar()
    assert resumo.revisao_humana == 1
    assert robo.repo.listar_revisoes()[0]["motivo"] == "conflito_sensor_ldr"


def test_leitura_diurna_do_sensor_e_ignorada(cfg):
    escrever_ldr(cfg, [(-498, 405, 900.0, NOITE.replace(hour=13))])  # sol do meio-dia não contesta
    escrever_relato(cfg, "a", -500, 400)
    resumo = fazer_robo(cfg).executar()
    assert resumo.chamados_criados == 1 and resumo.revisao_humana == 0


# ----------------------------------------------------- reincidência, SLA, abuso
def test_reincidencia_soma_pontos(cfg):
    repo = Repositorio(cfg.db_path)
    _chamado_historico(repo, "LS-20261106-0001", *_p(-645, -95), AGORA - timedelta(days=12), "resolvido",
                       ContextoPrioridade(rotulo="inexistente"), "x", resolvido=AGORA - timedelta(days=5))
    repo.fechar()
    escrever_relato(cfg, "a", -640, -90)
    robo = fazer_robo(cfg)
    robo.executar()
    novo = [c for c in robo.repo.listar_chamados() if c["status"] == "aberto"][0]
    assert novo["reincidente"] == 1 and "reincidencia" in novo["motivo_prioridade"]


def test_sla_vencido_e_escalonado_com_alerta(cfg):
    repo = Repositorio(cfg.db_path)
    # P3 (score 45) tem SLA de 7 dias; criado há 8 dias -> vencido
    _chamado_historico(repo, "LS-20261110-0001", *_p(705, -290), AGORA - timedelta(days=8), "aberto",
                       ContextoPrioridade(rotulo="inexistente", qtd_relatos=2), "x")
    repo.fechar()
    robo = fazer_robo(cfg)
    resumo = robo.executar()
    ch = robo.repo.chamado("LS-20261110-0001")
    assert resumo.escalados_sla == 1 and ch["status"] == "atrasado" and ch["atrasado"] == 1
    assert ler_jsonl(cfg.saida / "alertas.jsonl")[0]["tipo"] == "sla_vencido"
    # segunda execução não escalona de novo
    assert fazer_robo(cfg).executar().escalados_sla == 0


def test_muitos_relatos_do_mesmo_contato_vao_para_revisao(cfg):
    for i in range(6):
        escrever_relato(cfg, f"r{i}", -100, 700 + 90 * i, rotulo="fraca", minutos=5 * i,
                        contato="+55 11 91234-5678")
    robo = fazer_robo(cfg)
    resumo = robo.executar()
    assert resumo.chamados_criados == 5 and resumo.revisao_humana == 1
    assert robo.repo.listar_revisoes()[0]["motivo"] == "suspeita_abuso"


# ------------------------------------------------------------ idempotência
def test_reenvio_identico_e_ignorado(cfg):
    dados = escrever_relato(cfg, "original", 15, 13)
    fazer_robo(cfg).executar()
    (cfg.inbox / "reenvio.json").write_text(__import__("json").dumps(dados), encoding="utf-8")
    resumo = fazer_robo(cfg).executar()
    assert resumo.duplicados_ignorados == 1 and resumo.chamados_criados == 0


# ------------------------------------------------- pessoa no circuito (revisão)
def test_revisor_aprova_e_robo_cria_chamado_na_proxima_execucao(cfg):
    escrever_relato(cfg, "duvidoso", 200, -400, rotulo="inexistente", confianca=0.40)
    fazer_robo(cfg).executar()
    cliente = TestClient(criar_app(cfg))
    item = cliente.get("/revisao").json()[0]
    r = cliente.post(f"/revisao/{item['id']}/decisao", headers={"X-API-Key": "chave-teste"},
                     json={"decisao": "aprovar", "rotulo": "inexistente", "revisor": "Ana"})
    assert r.status_code == 200 and r.json()["reenfileirado"]

    robo = fazer_robo(cfg)
    resumo = robo.executar()
    assert resumo.chamados_criados == 1
    relato = robo.repo.relato(item["relato_id"])
    assert relato["fonte_visao"] == "revisor_humano" and relato["resultado"] == "chamado_criado"
    assert cliente.get("/revisao").json() == []


def test_revisor_rejeita_relato(cfg):
    escrever_relato(cfg, "duvidoso", 200, -400, confianca=0.40)
    fazer_robo(cfg).executar()
    cliente = TestClient(criar_app(cfg))
    item = cliente.get("/revisao").json()[0]
    r = cliente.post(f"/revisao/{item['id']}/decisao", headers={"X-API-Key": "chave-teste"},
                     json={"decisao": "rejeitar", "revisor": "Ana"})
    assert r.status_code == 200
    assert Repositorio(cfg.db_path).relato(item["relato_id"])["resultado"] == "improcedente"
