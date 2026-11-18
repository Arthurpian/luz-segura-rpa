"""CENÁRIOS DE SUCESSO: o caminho feliz de ponta a ponta."""
import json

import pytest

from conftest import NOITE, escrever_ldr, escrever_relato, fazer_robo, ler_jsonl

pytestmark = pytest.mark.sucesso


def test_relato_valido_vira_chamado_p1_com_alerta_e_exportacao(cfg):
    """Poste apagado ao lado do terminal (fluxo alto), sensor confirma, noite encoberta."""
    escrever_ldr(cfg, [(18, 10, 2.1, NOITE)])
    escrever_relato(cfg, "s01", 15, 13, rotulo="inexistente", confianca=0.93)

    resumo = fazer_robo(cfg).executar()

    assert resumo.status == "concluida"
    assert resumo.chamados_criados == 1 and resumo.alertas == 1 and resumo.erros == 0
    saida = json.loads((cfg.saida / "chamados.json").read_text(encoding="utf-8"))
    ch = saida["chamados"][0]
    assert ch["prioridade"] == "P1"
    assert ch["score"] == 75  # 40 severidade + 15 LDR + 15 parada fluxo alto + 5 clima
    assert {f["codigo"] for f in ch["fatores_prioridade"]} == {"severidade", "sensor_ldr", "parada_onibus", "clima"}
    assert ch["validacao_ldr"] == "confirmado" and ch["parada_id"] == "PAR-001"
    # saída também em GeoJSON para o mapa do MVP
    geo = json.loads((cfg.saida / "chamados.geojson").read_text(encoding="utf-8"))
    assert geo["features"][0]["geometry"]["type"] == "Point"
    # alerta registrado para a equipe de manutenção
    alertas = ler_jsonl(cfg.saida / "alertas.jsonl")
    assert alertas[0]["tipo"] == "novo_p1" and alertas[0]["chamado_id"] == ch["id"]
    # caixa de entrada esvaziada e foto original descartada (só a anonimizada fica)
    assert list(cfg.inbox.iterdir()) == []
    assert len(list(cfg.fotos.glob("*.jpg"))) == 1


def test_fluxo_completo_gera_logs_resumo_e_auditoria(cfg):
    escrever_relato(cfg, "a", 510, 615, rotulo="fraca", confianca=0.81)
    robo = fazer_robo(cfg)
    resumo = robo.executar()

    linhas = ler_jsonl(cfg.logs / "luzsegura_robo.jsonl")
    assert linhas, "o robô precisa gerar log estruturado"
    assert all(l["run_id"] == resumo.run_id for l in linhas)
    assert {"momento", "nivel", "mensagem"} <= set(linhas[0])
    assert (cfg.execucoes / f"{resumo.run_id}.json").exists()
    acoes = [r["acao"] for r in robo.repo.con.execute("SELECT acao FROM auditoria")]
    assert {"anonimizado", "classificado", "chamado_criado", "criado"} <= set(acoes)
    execucao = robo.repo.listar_execucoes(1)[0]
    assert execucao["status"] == "concluida" and execucao["resumo"]["lidos"] == 1


def test_lote_com_varios_relatos_e_processado_em_ordem(cfg):
    for i in range(5):
        escrever_relato(cfg, f"r{i}", -100, 700 + 120 * i, rotulo="fraca", confianca=0.8, minutos=i)
    resumo = fazer_robo(cfg).executar()
    assert resumo.lidos == 5 and resumo.chamados_criados == 5
    registro = json.loads((cfg.execucoes / f"{resumo.run_id}.json").read_text(encoding="utf-8"))
    assert registro["minutos_manuais_economizados"] == 30.0  # 5 relatos x 6 min (estimativa AS-IS)


def test_execucao_sem_relatos_conclui_sem_erro(cfg):
    resumo = fazer_robo(cfg).executar()
    assert resumo.status == "concluida" and resumo.lidos == 0
    assert json.loads((cfg.saida / "chamados.json").read_text(encoding="utf-8"))["total"] == 0
