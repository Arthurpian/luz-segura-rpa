"""INTEGRAÇÃO COM O MVP: o resultado do robô é consumido via API, banco e arquivos."""
import base64
import io
import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import NOITE, escrever_relato, fazer_robo
from luzsegura_rpa.api import criar_app
from luzsegura_rpa.dados_simulados import _p

pytestmark = pytest.mark.integracao
CHAVE = {"X-API-Key": "chave-teste"}


def _foto_b64(luminancia=8):
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (luminancia,) * 3).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_app_envia_relato_pela_api_e_robo_processa(cfg):
    cliente = TestClient(criar_app(cfg))
    lat, lon = _p(15, 13)
    corpo = {"id": str(uuid.uuid4()), "criado_em": NOITE.isoformat(), "latitude": lat, "longitude": lon,
             "canal": "app", "foto_base64": _foto_b64()}
    r = cliente.post("/relatos", json=corpo, headers=CHAVE)
    assert r.status_code == 202 and r.json()["status"] == "na_fila"
    assert cliente.post("/relatos", json=corpo, headers=CHAVE).status_code == 409

    resumo = fazer_robo(cfg).executar()
    assert resumo.chamados_criados == 1
    chamados = cliente.get("/chamados").json()
    assert chamados[0]["fatores_prioridade"] and chamados[0]["motivo_prioridade"].startswith("P")


def test_detalhe_do_chamado_traz_explicacao_relatos_e_auditoria(cfg):
    escrever_relato(cfg, "a", 15, 13)
    escrever_relato(cfg, "b", 20, 18, minutos=5)
    fazer_robo(cfg).executar()
    cliente = TestClient(criar_app(cfg))
    cid = cliente.get("/chamados").json()[0]["id"]
    d = cliente.get(f"/chamados/{cid}").json()
    assert len(d["relatos"]) == 2 and d["auditoria"]
    assert cliente.get("/chamados/LS-NAO-EXISTE").status_code == 404


def test_manutencao_resolve_chamado_e_indicador_de_conserto_e_calculado(cfg):
    escrever_relato(cfg, "a", 15, 13)
    fazer_robo(cfg).executar()
    cliente = TestClient(criar_app(cfg))
    cid = cliente.get("/chamados").json()[0]["id"]
    r = cliente.patch(f"/chamados/{cid}/status", json={"status": "resolvido", "responsavel": "Equipe 3"}, headers=CHAVE)
    assert r.status_code == 200 and r.json()["status"] == "resolvido"
    assert cliente.patch(f"/chamados/{cid}/status", json={"status": "resolvido", "responsavel": "Equipe 3"},
                         headers=CHAVE).status_code == 409
    assert cliente.get("/indicadores").json()["tempo_medio_ate_conserto_h"] is not None


def test_outro_componente_le_direto_do_banco_e_dos_arquivos(cfg):
    escrever_relato(cfg, "a", 15, 13)
    fazer_robo(cfg).executar()
    # pipeline de dados / painel BI lendo o SQLite
    con = sqlite3.connect(cfg.db_path)
    assert con.execute("SELECT prioridade, score FROM chamados").fetchall() == [("P2", 60)]
    # app ou RAG lendo o JSON exportado (contrato versionado)
    saida = json.loads((cfg.saida / "chamados.json").read_text(encoding="utf-8"))
    assert saida["versao_contrato"] == "1.0" and saida["total"] == 1


def test_painel_e_endpoints_de_leitura_respondem(cfg):
    fazer_robo(cfg).executar()
    cliente = TestClient(criar_app(cfg))
    assert cliente.get("/").status_code == 200
    assert cliente.get("/static/vendor/leaflet/leaflet.js").status_code == 200
    assert cliente.get("/health").json()["ultima_execucao"]["status"] == "concluida"
    ref = cliente.get("/referencias").json()
    assert ref["territorio"]["features"] and len(ref["pontos"]) == 12
    assert cliente.get("/execucoes").json()
    assert cliente.post("/robo/executar", headers=CHAVE).json()["status"] == "concluida"
