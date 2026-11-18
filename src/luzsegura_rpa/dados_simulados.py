"""Gerador de dados simulados (permitido pelo briefing, com geração documentada).

Cria um território-piloto no Centro de Osasco/SP, pontos de referência no
formato GTFS (stops.txt + tipo/fluxo), leituras do sensor LDR, fotos
noturnas sintéticas (com EXIF falso para provar a anonimização) e 24 relatos
que cobrem todos os caminhos do processo: sucesso, decisões e falhas.

Coordenadas e nomes são SIMULADOS (coluna origem=simulado). Para usar dados
reais basta trocar data/referencia/pontos_referencia.csv por um stops.txt
de GTFS (EMTU/SPTrans) com as colunas extras `tipo` e `fluxo`.
"""
from __future__ import annotations

import csv
import json
import random
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageStat

from .banco import Repositorio
from .config import Config
from .geo import deslocar
from .regras import ContextoPrioridade, calcular_prioridade

CENTRO = (-23.5320, -46.7880)  # Centro de Osasco (aproximado)

# id, nome, norte_m, leste_m, tipo, fluxo
PONTOS = [
    ("PAR-001", "Parada Terminal Centro", 0, 0, "parada_onibus", "alto"),
    ("PAR-002", "Parada Avenida Principal", 300, 250, "parada_onibus", "alto"),
    ("PAR-003", "Parada Rua Comercial", -400, 150, "parada_onibus", "medio"),
    ("PAR-004", "Parada Bairro Norte", 700, -300, "parada_onibus", "baixo"),
    ("PAR-005", "Parada Hospital", -200, -500, "parada_onibus", "alto"),
    ("PAR-006", "Parada Escola Estadual", 500, 600, "parada_onibus", "medio"),
    ("PAR-007", "Parada Praça Central", -650, -100, "parada_onibus", "medio"),
    ("PAR-008", "Parada Vila Leste", 900, 400, "parada_onibus", "baixo"),
    ("EST-001", "Estação de trem", 100, -150, "estacao", None),
    ("ESC-001", "Escola Estadual", 520, 640, "escola", None),
    ("UBS-001", "UBS Centro", -220, -540, "ubs", None),
    ("PRA-001", "Praça Central", -660, -80, "praca", None),
]


def _p(norte: float, leste: float) -> tuple[float, float]:
    lat, lon = deslocar(*CENTRO, norte, leste)
    return round(lat, 6), round(lon, 6)


def gerar_referencias(cfg: Config) -> None:
    cfg.referencia.mkdir(parents=True, exist_ok=True)
    import math
    raio = 1600
    anel = []
    for i in range(7):
        ang = math.radians(60 * (i % 6) + 30)
        lat, lon = _p(raio * math.sin(ang), raio * math.cos(ang))
        anel.append([lon, lat])
    territorio = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"nome": "Piloto Centro de Osasco (simulado)",
                       "observacao": "Polígono hexagonal de ~1,6 km em torno do centro. Substituir pelo limite real do bairro."},
        "geometry": {"type": "Polygon", "coordinates": [anel]},
    }]}
    cfg.territorio_path.write_text(json.dumps(territorio, ensure_ascii=False, indent=2), encoding="utf-8")

    with cfg.pontos_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stop_id", "stop_name", "stop_lat", "stop_lon", "tipo", "fluxo", "origem"])
        for pid, nome, n, e, tipo, fluxo in PONTOS:
            lat, lon = _p(n, e)
            w.writerow([pid, nome, lat, lon, tipo, fluxo or "", "simulado"])


def gerar_foto(destino: Path, luminancia: float, semente: int, com_exif: bool = True) -> None:
    """Foto noturna sintética 640x480 com poste; luminância média controlada."""
    rnd = random.Random(semente)
    img = Image.effect_noise((640, 480), 18).convert("L")
    draw = ImageDraw.Draw(img)
    x = rnd.randint(180, 460)
    draw.rectangle([x, 120, x + 8, 480], fill=40)                      # poste
    draw.rectangle([x - 30, 110, x + 10, 122], fill=50)                 # braço
    if luminancia > 80:
        draw.ellipse([x - 160, 60, x + 120, 330], fill=235)             # luz acesa
    elif luminancia > 35:
        draw.ellipse([x - 60, 95, x + 20, 170], fill=150)               # luz fraca
    img = img.filter(ImageFilter.GaussianBlur(6))
    media = ImageStat.Stat(img).mean[0]
    img = img.point(lambda v: max(0, min(255, int(v + (luminancia - media)))))
    rgb = Image.merge("RGB", (img, img, img.point(lambda v: min(255, v + 12))))
    destino.parent.mkdir(parents=True, exist_ok=True)
    if com_exif:
        exif = Image.Exif()
        exif[0x010F] = "SimPhone"
        exif[0x0110] = "Modelo-Ficticio-X"
        exif[0x0132] = "2026:11:17 21:00:00"
        exif[0x8825] = {1: "S", 2: (23.0, 31.0, 55.2), 3: "W", 4: (46.0, 47.0, 16.8)}
        rgb.save(destino, quality=88, exif=exif)
    else:
        rgb.save(destino, quality=88)


def _limpar(cfg: Config) -> None:
    if cfg.inbox.exists():
        for arq in cfg.inbox.iterdir():
            if arq.is_file() and arq.name != ".gitkeep":
                arq.unlink()
    for pasta in (cfg.quarentena, cfg.erros, cfg.processados, cfg.fotos, cfg.saida, cfg.execucoes):
        if pasta.exists():
            shutil.rmtree(pasta)
    for arq in (cfg.db_path, cfg.lock_path, cfg.logs / "luzsegura_robo.jsonl", *cfg.logs.glob("luzsegura_robo.jsonl.*")):
        if arq.exists():
            try:
                arq.unlink()
            except PermissionError:
                # Windows: arquivo aberto por outro processo (ex.: a API rodando). Esvazia em vez de apagar.
                if arq.suffix != ".db":
                    arq.write_text("", encoding="utf-8")
                else:
                    raise PermissionError(f"Feche a API (python main.py api) antes do seed: {arq.name} está em uso")
    cfg.garantir_pastas()


def _relato(cfg: Config, nome: str, rid: str, momento: datetime, lat: float, lon: float, luminancia: float,
            semente: int, **campos) -> dict:
    foto = f"{rid}.jpg"
    gerar_foto(cfg.inbox / foto, luminancia, semente)
    dados = {"id": rid, "criado_em": momento.isoformat(timespec="seconds"), "latitude": lat, "longitude": lon,
             "foto": foto, "canal": "app", **campos}
    (cfg.inbox / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return dados


def _chamado_historico(repo: Repositorio, cid: str, lat: float, lon: float, criado: datetime, status: str,
                       ctx: ContextoPrioridade, parada: str, resolvido: datetime | None = None) -> None:
    res = calcular_prioridade(ctx)
    repo.inserir_chamado({
        "id": cid, "status": status, "latitude": lat, "longitude": lon, "rotulo_visao": ctx.rotulo,
        "confianca_visao": 0.9, "validacao_ldr": ctx.validacao_ldr, "lux_medido": ctx.lux_medido,
        "parada_id": ctx.parada_id, "parada_nome": parada, "distancia_parada_m": ctx.distancia_parada_m,
        "fluxo_parada": ctx.fluxo_parada, "pontos_sensiveis": json.dumps(ctx.pontos_sensiveis, ensure_ascii=False),
        "qtd_relatos": ctx.qtd_relatos, "eh_noite": 1, "nebulosidade_pct": None, "visibilidade_m": None,
        "clima_indisponivel": 0, "reincidente": 0, "atrasado": 0, "score": res.score, "prioridade": res.prioridade,
        "motivo_prioridade": res.motivo_json(), "criado_em": criado.isoformat(timespec="seconds"),
        "atualizado_em": criado.isoformat(timespec="seconds"),
        "prazo_sla": (criado + timedelta(hours=res.sla_horas)).isoformat(timespec="seconds"),
        "resolvido_em": resolvido.isoformat(timespec="seconds") if resolvido else None,
        "run_id_origem": "HISTORICO-SIMULADO",
    })


def gerar_cenarios(cfg: Config, agora: datetime | None = None, limpar: bool = True) -> list[dict]:
    """Gera referências, sensores, histórico e relatos. Retorna a tabela de cenários esperados."""
    if limpar:
        _limpar(cfg)
    cfg.garantir_pastas()
    gerar_referencias(cfg)
    tz = ZoneInfo(cfg.fuso)
    agora = (agora or datetime.now(tz)).astimezone(tz)
    noite = (agora - timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
    novo_id = lambda: str(uuid.uuid4())  # noqa: E731

    s01 = _p(15, 13)                 # ao lado do Terminal Centro (fluxo alto)
    s04 = _p(510, 615)               # entre a Parada Escola e a Escola Estadual
    s07 = _p(-500, 400)              # sensor contesta
    s13 = _p(-390, 160)              # Parada Rua Comercial
    s16 = _p(-640, -90)              # Praça Central: poste consertado que voltou a falhar
    hist_resolvido = _p(-645, -95)
    hist_atrasado = _p(705, -290)    # Parada Bairro Norte

    # ---- Sensor LDR (Maker Lab): leituras noturnas + 1 linha inválida
    with cfg.ldr_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dispositivo", "lido_em", "latitude", "longitude", "lux"])
        w.writerow(["LDR-01", (noite - timedelta(hours=1)).isoformat(timespec="seconds"), *_p(18, 10), 2.1])
        w.writerow(["LDR-01", (noite - timedelta(hours=2)).isoformat(timespec="seconds"), *_p(505, 612), 8.4])
        w.writerow(["LDR-02", (noite - timedelta(minutes=30)).isoformat(timespec="seconds"), *_p(-498, 405), 42.0])
        rnd = random.Random(7)
        for i in range(12):
            w.writerow([f"LDR-0{1 + i % 2}", (noite - timedelta(hours=rnd.randint(1, 48))).isoformat(timespec="seconds"),
                        *_p(rnd.randint(-1200, 1200), rnd.randint(-1200, 1200)), round(rnd.uniform(20, 60), 1)])
        w.writerow(["LDR-02", "ontem a noite", "x", "y", "muito escuro"])   # linha inválida proposital

    # ---- Histórico no banco (para reincidência e SLA)
    repo = Repositorio(cfg.db_path)
    _chamado_historico(repo, f"LS-{(agora - timedelta(days=12)):%Y%m%d}-0001", *hist_resolvido,
                       agora - timedelta(days=12), "resolvido",
                       ContextoPrioridade(rotulo="inexistente", parada_id="PAR-007", distancia_parada_m=8,
                                          fluxo_parada="medio", pontos_sensiveis=["Praça Central"]),
                       "Parada Praça Central", resolvido=agora - timedelta(days=5))
    _chamado_historico(repo, f"LS-{(agora - timedelta(days=4)):%Y%m%d}-0001", *hist_atrasado,
                       agora - timedelta(days=4), "aberto",
                       ContextoPrioridade(rotulo="inexistente", parada_id="PAR-004", distancia_parada_m=12,
                                          fluxo_parada="baixo", qtd_relatos=2),
                       "Parada Bairro Norte")
    repo.fechar()

    c = []  # tabela de cenários

    def add(codigo, titulo, esperado, tipo):
        c.append({"codigo": codigo, "titulo": titulo, "esperado": esperado, "tipo": tipo})

    id01 = novo_id()
    _relato(cfg, "01_sucesso_p1", id01, noite, *s01, 8, 1,
            descricao="Ponto do terminal completamente escuro",
            classificacao_visao={"rotulo": "inexistente", "confianca": 0.93, "fonte": "app_visao"})
    add("S01", "Poste apagado ao lado do terminal, sensor confirma", "chamado P1 + alerta", "sucesso")

    _relato(cfg, "02_dedup_mesmo_ponto", novo_id(), noite + timedelta(minutes=10), *_p(22, 20), 10, 2,
            classificacao_visao={"rotulo": "inexistente", "confianca": 0.9, "fonte": "app_visao"})
    add("S02", "Segundo relato a ~10 m do S01", "mesclado (2 relatos)", "decisao")

    _relato(cfg, "03_dedup_terceiro", novo_id(), noite + timedelta(minutes=25), *_p(8, 5), 9, 3)
    add("S03", "Terceiro relato no mesmo ponto, sem classificação do app", "mesclado (3 relatos, heurística)", "decisao")

    id04 = novo_id()
    d04 = _relato(cfg, "04_fraca_escola", id04, noite + timedelta(minutes=40), *s04, 55, 4,
                  classificacao_visao={"rotulo": "fraca", "confianca": 0.81, "fonte": "app_visao"})
    add("S04", "Luz fraca entre a parada e a escola, sensor confirma", "chamado P2", "sucesso")

    id05 = novo_id()
    d05 = _relato(cfg, "05_iluminacao_adequada", id05, noite + timedelta(minutes=50), *_p(-300, 300), 170, 5,
                  classificacao_visao={"rotulo": "adequada", "confianca": 0.93, "fonte": "app_visao"})
    add("S05", "Foto mostra rua bem iluminada", "improcedente", "decisao")

    _relato(cfg, "06_baixa_confianca", novo_id(), noite + timedelta(minutes=55), *_p(200, -400), 34, 6)
    add("S06", "Foto ambígua (luminância no limiar)", "revisão humana (baixa confiança)", "decisao")

    _relato(cfg, "07_conflito_sensor", novo_id(), noite + timedelta(hours=1), *s07, 12, 7,
            classificacao_visao={"rotulo": "inexistente", "confianca": 0.9, "fonte": "app_visao"})
    add("S07", "Foto escura, mas o sensor mediu 42 lux", "revisão humana (conflito LDR)", "decisao")

    _relato(cfg, "08_fora_territorio", novo_id(), noite + timedelta(hours=1, minutes=5), -23.5505, -46.6333, 10, 8)
    add("S08", "Relato na Praça da Sé (fora do piloto)", "quarentena: fora_do_territorio", "falha")

    (cfg.inbox / "09_json_corrompido.json").write_text('{"id": "a1b2c3d4e5", "latitude": -23.53, "longitu',
                                                       encoding="utf-8")
    add("S09", "Arquivo JSON truncado", "quarentena: json_invalido", "falha")

    rid = novo_id()
    (cfg.inbox / "10_foto_ausente.json").write_text(json.dumps({
        "id": rid, "criado_em": (noite + timedelta(hours=1)).isoformat(), "latitude": s04[0] + 0.003,
        "longitude": s04[1], "foto": "foto_que_nao_existe.jpg"}, indent=2), encoding="utf-8")
    add("S10", "Relato sem a foto correspondente", "quarentena: foto_ausente", "falha")

    _relato(cfg, "11_data_futura", novo_id(), agora + timedelta(days=2), *_p(100, 100), 10, 11)
    add("S11", "Data de criação no futuro", "quarentena: data_futura", "falha")

    (cfg.inbox / "12_schema_invalido.json").write_text(json.dumps({
        "id": "x", "criado_em": "ontem", "latitude": "abc", "longitude": -46.78}, indent=2), encoding="utf-8")
    add("S12", "Campos com tipo errado e obrigatórios faltando", "quarentena: schema_invalido", "falha")

    _relato(cfg, "13_pii_na_descricao", novo_id(), noite + timedelta(hours=1, minutes=20), *s13, 10, 13,
            descricao="Poste apagado em frente ao nº 120. Me liguem (11) 98765-4321 ou joao.silva@email.com, "
                      "tem um carro ABC1D23 parado no escuro",
            contato="joao.silva@email.com")
    add("S13", "Descrição com telefone, e-mail e placa", "chamado P2 com PII mascarada", "sucesso")

    (cfg.inbox / "14_duplicado_exato.json").write_text(json.dumps(d04, ensure_ascii=False, indent=2), encoding="utf-8")
    add("S14", "Reenvio idêntico do S04 (app reenviou)", "ignorado (idempotência)", "decisao")

    d15 = {**d05, "descricao": "editei o texto depois"}
    gerar_foto(cfg.inbox / "conflito.jpg", 170, 15)
    d15["foto"] = "conflito.jpg"
    (cfg.inbox / "15_conflito_id.json").write_text(json.dumps(d15, ensure_ascii=False, indent=2), encoding="utf-8")
    add("S15", "Mesmo id do S05 com conteúdo diferente", "quarentena: conflito_id", "falha")

    _relato(cfg, "16_reincidencia", novo_id(), noite + timedelta(hours=1, minutes=30), *s16, 9, 16,
            classificacao_visao={"rotulo": "inexistente", "confianca": 0.88, "fonte": "app_visao"})
    add("S16", "Poste da praça consertado há 5 dias voltou a apagar", "chamado P1 (reincidência) + alerta", "decisao")

    contato_abuso = "+55 11 91234-5678"
    for i in range(6):
        _relato(cfg, f"17_abuso_{i + 1}", novo_id(), noite + timedelta(hours=2, minutes=5 * i),
                *_p(-100, 700 + 90 * i), 55, 170 + i, contato=contato_abuso,
                classificacao_visao={"rotulo": "fraca", "confianca": 0.8, "fonte": "app_visao"})
    add("S17", "6 relatos do mesmo contato em 25 min", "5 chamados (P4; P3 se a noite estava encoberta) + 1 revisão (suspeita_abuso)", "decisao")

    rid = novo_id()
    (cfg.inbox / f"{rid}.jpg").write_bytes(b"isto nao e uma imagem" * 20)
    (cfg.inbox / "18_foto_corrompida.json").write_text(json.dumps({
        "id": rid, "criado_em": (noite + timedelta(hours=3)).isoformat(), "latitude": s01[0] - 0.004,
        "longitude": s01[1], "foto": f"{rid}.jpg"}, indent=2), encoding="utf-8")
    add("S18", "Arquivo .jpg que não é imagem", "quarentena: foto_corrompida", "falha")

    _relato(cfg, "19_expirado", novo_id(), agora - timedelta(days=10), *_p(-50, -600), 10, 19)
    add("S19", "Relato de 10 dias atrás", "quarentena: relato_expirado", "falha")

    add("S20", "Chamado histórico com SLA vencido (PAR-004)", "escalonado para 'atrasado' + alerta", "decisao")
    add("S21", "Open-Meteo fora do ar / sem internet", "retry + circuit breaker + fallback, chamados seguem",
        "falha")
    return c
