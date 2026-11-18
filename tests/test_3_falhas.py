"""CENÁRIOS DE FALHA: entradas ruins, serviços fora do ar e erros inesperados.

Regra de ouro: nenhuma falha é silenciosa e nenhuma falha de um item para o lote.
"""
import json
import os
import time

import pytest
import requests

from conftest import AGORA, NOITE, OpenMeteoFalsa, escrever_relato, fazer_robo, ler_jsonl
from luzsegura_rpa.resiliencia import CircuitBreaker, ExecucaoConcorrente, TravaExecucao
from luzsegura_rpa.robo import reprocessar_erros
from luzsegura_rpa.servicos.notificador import Notificador

pytestmark = pytest.mark.falha


def _motivo(cfg, motivo):
    pasta = cfg.quarentena / motivo
    fichas = list(pasta.glob("*.motivo.json"))
    assert fichas, f"esperava ficha de quarentena em {pasta}"
    return json.loads(fichas[0].read_text(encoding="utf-8"))


# ------------------------------------------------------- arquivos inválidos
def test_json_corrompido_vai_para_quarentena(cfg):
    (cfg.inbox / "quebrado.json").write_text('{"id": "abc12345", "latit', encoding="utf-8")
    resumo = fazer_robo(cfg).executar()
    assert resumo.quarentena == 1 and resumo.status == "concluida"
    assert _motivo(cfg, "json_invalido")["arquivo"] == "quebrado.json"


def test_schema_invalido_lista_os_campos(cfg):
    (cfg.inbox / "ruim.json").write_text(json.dumps({"id": "x", "latitude": "abc"}), encoding="utf-8")
    fazer_robo(cfg).executar()
    detalhe = _motivo(cfg, "schema_invalido")["detalhe"]
    assert "latitude" in detalhe and "foto" in detalhe and "criado_em" in detalhe


def test_tentativa_de_path_traversal_na_foto_e_bloqueada(cfg):
    escrever_relato(cfg, "ataque", 15, 13, foto="../../segredo.jpg", gerar_foto=False)
    fazer_robo(cfg).executar()
    assert "foto" in _motivo(cfg, "schema_invalido")["detalhe"]


def test_foto_ausente(cfg):
    escrever_relato(cfg, "sem_foto", 15, 13, foto="nao_existe.jpg", gerar_foto=False)
    resumo = fazer_robo(cfg).executar()
    assert resumo.quarentena == 1
    _motivo(cfg, "foto_ausente")


def test_foto_corrompida(cfg):
    dados = escrever_relato(cfg, "corrompida", 15, 13, gerar_foto=False, foto="lixo.jpg")
    (cfg.inbox / dados["foto"]).write_bytes(b"nao sou imagem" * 50)
    fazer_robo(cfg).executar()
    _motivo(cfg, "foto_corrompida")
    assert (cfg.quarentena / "foto_corrompida" / "lixo.jpg").exists()  # foto vai junto para análise


def test_fora_do_territorio(cfg):
    escrever_relato(cfg, "se", 0, 0)
    arq = cfg.inbox / "se.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    dados.update(latitude=-23.5505, longitude=-46.6333)  # Praça da Sé
    arq.write_text(json.dumps(dados), encoding="utf-8")
    fazer_robo(cfg).executar()
    _motivo(cfg, "fora_do_territorio")


def test_data_futura_e_relato_expirado(cfg):
    escrever_relato(cfg, "futuro", 15, 13, criado_em=AGORA.replace(day=20))
    escrever_relato(cfg, "velho", 300, 13, criado_em=AGORA.replace(day=1))
    resumo = fazer_robo(cfg).executar()
    assert resumo.quarentena == 2
    _motivo(cfg, "data_futura")
    _motivo(cfg, "relato_expirado")


def test_mesmo_id_com_conteudo_diferente_e_conflito(cfg):
    dados = escrever_relato(cfg, "a", 15, 13, descricao="original")
    fazer_robo(cfg).executar()
    escrever_relato(cfg, "b", 15, 13, id=dados["id"], descricao="alterado")
    resumo = fazer_robo(cfg).executar()
    assert resumo.quarentena == 1
    _motivo(cfg, "conflito_id")


def test_linhas_invalidas_do_sensor_nao_derrubam_o_lote(cfg):
    cfg.ldr_path.write_text("dispositivo,lido_em,latitude,longitude,lux\nLDR,ontem,x,y,escuro\n"
                            f"LDR,{NOITE.isoformat()},-23.53,-46.78,-5\n", encoding="utf-8")
    escrever_relato(cfg, "a", 15, 13)
    resumo = fazer_robo(cfg).executar()
    assert resumo.leituras_ldr_invalidas == 2 and resumo.chamados_criados == 1


# --------------------------------------------------- serviços externos fora
def test_open_meteo_fora_do_ar_retry_circuit_breaker_e_fallback(cfg):
    api = OpenMeteoFalsa(modo="offline")
    for i in range(5):
        escrever_relato(cfg, f"r{i}", -100, 700 + 120 * i, rotulo="fraca", minutos=i)
    robo = fazer_robo(cfg, api)
    resumo = robo.executar()
    assert resumo.chamados_criados == 5 and resumo.erros == 0      # o processo não para
    assert resumo.clima_degradado == 5
    assert api.chamadas == 9      # 3 relatos x 3 tentativas; depois o circuito abre e poupa as demais
    assert robo.clima.circuito.estado == "aberto"
    assert all(c["clima_indisponivel"] for c in robo.repo.listar_chamados())


def test_open_meteo_com_resposta_inesperada_usa_fallback(cfg):
    escrever_relato(cfg, "a", 15, 13)
    resumo = fazer_robo(cfg, OpenMeteoFalsa(modo="resposta_estranha")).executar()
    assert resumo.chamados_criados == 1 and resumo.clima_degradado == 1


def test_api_de_visao_fora_usa_heuristica(cfg, tmp_path):
    from dataclasses import replace
    from luzsegura_rpa.servicos.visao import ServicoVisao

    class VisaoOffline:
        def post(self, *a, **k):
            raise requests.ConnectionError("visão fora")

    cfg2 = replace(cfg, visao_api_url="http://visao.invalida/classificar")
    escrever_relato(cfg2, "a", 15, 13, rotulo=None, luminancia=9)
    robo = fazer_robo(cfg2, visao=ServicoVisao(cfg2, sessao=VisaoOffline(), dormir=lambda s: None))
    resumo = robo.executar()
    assert resumo.visao_degradada == 1 and resumo.chamados_criados == 1


def test_webhook_fora_do_ar_mantem_alerta_no_arquivo(cfg, caplog):
    from dataclasses import replace

    class WebhookOffline:
        def post(self, *a, **k):
            raise requests.ConnectionError("webhook fora")

    cfg2 = replace(cfg, webhook_alerta_url="http://webhook.invalido")
    canais = Notificador(cfg2, sessao=WebhookOffline()).alertar(
        "teste", {"id": "LS-1", "prioridade": "P1", "score": 80, "latitude": 0, "longitude": 0}, "msg", AGORA)
    assert canais == ["arquivo"]
    assert ler_jsonl(cfg2.saida / "alertas.jsonl")[0]["chamado_id"] == "LS-1"


def test_circuit_breaker_reabre_depois_do_tempo():
    relogio = [0.0]
    cb = CircuitBreaker("x", limite_falhas=2, reabrir_em_s=10, relogio=lambda: relogio[0])
    cb.falha(), cb.falha()
    assert cb.estado == "aberto" and not cb.permitir()
    relogio[0] = 11
    assert cb.estado == "meio_aberto" and cb.permitir()
    cb.sucesso()
    assert cb.estado == "fechado"


# ------------------------------------------------------- erros inesperados
def test_erro_inesperado_vai_para_dead_letter_e_lote_continua(cfg):
    escrever_relato(cfg, "a_vai_falhar", 15, 13)
    escrever_relato(cfg, "b_ok", 500, 600)
    robo = fazer_robo(cfg)
    original = robo.clima.obter
    estado = {"primeira": True}

    def obter_com_bug(*a, **k):
        if estado["primeira"]:
            estado["primeira"] = False
            raise RuntimeError("bug simulado no enriquecimento")
        return original(*a, **k)

    robo.clima.obter = obter_com_bug
    resumo = robo.executar()
    assert resumo.erros == 1 and resumo.chamados_criados == 1
    assert resumo.status == "concluida_com_erros"
    ficha = json.loads((cfg.erros / "a_vai_falhar.erro.json").read_text(encoding="utf-8"))
    assert ficha["tipo"] == "RuntimeError"
    assert any(l["nivel"] == "ERROR" and l.get("resultado") == "dead_letter"
               for l in ler_jsonl(cfg.logs / "luzsegura_robo.jsonl"))

    # recuperação: reprocessar a dead letter
    assert reprocessar_erros(cfg) == 1
    resumo2 = fazer_robo(cfg).executar()
    assert resumo2.chamados_criados == 1 and resumo2.erros == 0


def test_territorio_ausente_interrompe_execucao_sem_perder_relatos(cfg):
    escrever_relato(cfg, "a", 15, 13)
    cfg.territorio_path.unlink()
    resumo = fazer_robo(cfg).executar()
    assert resumo.status == "falhou"
    assert (cfg.inbox / "a.json").exists()  # nada foi perdido


def test_duas_execucoes_ao_mesmo_tempo_sao_bloqueadas(cfg):
    with TravaExecucao(cfg.lock_path):
        with pytest.raises(ExecucaoConcorrente):
            fazer_robo(cfg).executar()
    assert not cfg.lock_path.exists()


def test_trava_antiga_e_removida(cfg):
    cfg.lock_path.write_text("pid=999")
    antigo = time.time() - 3600
    os.utime(cfg.lock_path, (antigo, antigo))
    assert fazer_robo(cfg).executar().status == "concluida"
