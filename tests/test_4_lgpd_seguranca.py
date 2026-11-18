"""LGPD e segurança: dados pessoais não chegam ao banco, aos logs nem à API."""
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import escrever_relato, fazer_robo
from luzsegura_rpa.api import criar_app
from luzsegura_rpa.lgpd import mascarar_texto, pseudonimizar

pytestmark = pytest.mark.lgpd

EMAIL = "joao.silva@email.com"
TELEFONE = "(11) 98765-4321"


def test_mascaramento_de_texto():
    texto = f"me liguem {TELEFONE} ou {EMAIL}, CPF 123.456.789-09, carro ABC1D23"
    limpo = mascarar_texto(texto)
    for dado in (TELEFONE, EMAIL, "123.456.789-09", "ABC1D23"):
        assert dado not in limpo
    # identificadores técnicos não podem ser mascarados por engano
    assert mascarar_texto("chamado LS-20261117-0001 RUN-20261118T105500-ab12") == \
        "chamado LS-20261117-0001 RUN-20261118T105500-ab12"


def test_pseudonimizacao_e_estavel_e_irreversivel():
    a = pseudonimizar("+55 (11) 91234-5678", "s")
    assert a == pseudonimizar("+5511912345678", "s") and len(a) == 16 and "9123" not in a
    assert pseudonimizar("+5511912345678", "outro-salt") != a


def test_relato_com_pii_nao_vaza_para_banco_logs_nem_api(cfg):
    escrever_relato(cfg, "pii", -390, 160, descricao=f"Poste apagado. Me liguem {TELEFONE} ou {EMAIL}",
                    contato=EMAIL)
    robo = fazer_robo(cfg)
    robo.executar()

    relato = dict(robo.repo.con.execute("SELECT * FROM relatos").fetchone())
    assert EMAIL not in json.dumps(relato) and "98765" not in json.dumps(relato)
    assert relato["contato_hash"] == pseudonimizar(EMAIL, cfg.salt_pseudonimizacao)
    robo.repo.fechar()
    assert EMAIL.encode() not in cfg.db_path.read_bytes()
    assert EMAIL not in (cfg.logs / "luzsegura_robo.jsonl").read_text(encoding="utf-8")

    api = TestClient(criar_app(cfg)).get("/chamados").json()
    assert EMAIL not in json.dumps(api) and "contato" not in json.dumps(api)


def test_exif_e_gps_sao_removidos_da_foto(cfg):
    dados = escrever_relato(cfg, "foto", 15, 13)
    with Image.open(cfg.inbox / dados["foto"]) as original:
        assert original.getexif().get_ifd(0x8825), "a foto de teste precisa ter GPS no EXIF"
    fazer_robo(cfg).executar()
    with Image.open(cfg.fotos / f"{dados['id']}.jpg") as limpa:
        assert not limpa.getexif()
        assert max(limpa.size) <= 1280


def test_escrita_na_api_exige_chave(cfg):
    cliente = TestClient(criar_app(cfg))
    assert cliente.post("/robo/executar").status_code == 401
    assert cliente.post("/robo/executar", headers={"X-API-Key": "errada"}).status_code == 401
    assert cliente.patch("/chamados/LS-1/status", json={"status": "resolvido", "responsavel": "x"}).status_code == 401
