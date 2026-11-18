"""Gera docs/processo_luzsegura.bpmn (BPMN 2.0 com diagrama) e docs/fluxo_bpmn.png.

O .bpmn abre no Camunda Modeler, no bpmn.io (demo.bpmn.io) ou no Bizagi.
O PNG é desenhado a partir das MESMAS coordenadas, então os dois sempre batem.

    python scripts/gerar_bpmn.py
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"

W, H = 1960, 1100

# ----------------------------------------------------------------- modelo
# kind: start | start_timer | start_msg | end | end_msg | task | user | service | gw | sub | boundary_err
N: dict[str, dict] = {}


def no(id_, kind, nome, cx, cy, proc, w=None, h=None, rotulo=None, mi=False, pai=None, preso=None):
    if kind in ("start", "start_timer", "start_msg", "end", "end_msg", "boundary_err"):
        w = h = 32 if kind != "boundary_err" else 28
    elif kind == "gw":
        w = h = 46
    N[id_] = dict(id=id_, kind=kind, nome=nome, x=cx - w / 2, y=cy - h / 2, w=w, h=h, cx=cx, cy=cy,
                  proc=proc, rotulo=rotulo, mi=mi, pai=pai, preso=preso)


def caixa(id_, kind, nome, x, y, w, h, proc, mi=False):
    N[id_] = dict(id=id_, kind=kind, nome=nome, x=x, y=y, w=w, h=h, cx=x + w / 2, cy=y + h / 2, proc=proc,
                  rotulo=None, mi=mi, pai=None, preso=None)


def R(i):
    n = N[i]; return (n["x"] + n["w"], n["cy"])  # noqa: E702


def L(i):
    n = N[i]; return (n["x"], n["cy"])  # noqa: E702


def T(i, dx=0):
    n = N[i]; return (n["cx"] + dx, n["y"])  # noqa: E702


def B(i, dx=0):
    n = N[i]; return (n["cx"] + dx, n["y"] + n["h"])  # noqa: E702


POOLS = [
    ("Pool_Cidadao", "Proc_Cidadao", "Cidadão", 20, 20, 1920, 110),
    ("Pool_Robo", "Proc_Robo", "Robô RPA Luz Segura (Python)", 20, 150, 1920, 620),
    ("Pool_Revisor", "Proc_Revisor", "Revisor humano", 20, 790, 1920, 150),
    ("Pool_Manut", "Proc_Manut", "Manutenção", 20, 960, 1920, 120),
]

# ---- Cidadão
no("c_ini", "start", "Encontrou ponto escuro", 100, 75, "Proc_Cidadao", rotulo="below")
no("c_foto", "user", "Fotografar e enviar (foto + GPS)", 215, 75, "Proc_Cidadao", 120, 56)
no("c_app", "service", "App grava relato (POST /relatos)", 370, 75, "Proc_Cidadao", 130, 56)
no("c_fim", "end", "Relato na fila", 490, 75, "Proc_Cidadao", rotulo="below")

# ---- Robô: linha principal
no("r_ini", "start_timer", "A cada 15 min", 100, 215, "Proc_Robo", rotulo="below")
no("r_trava", "service", "Obter trava e gerar run_id", 205, 215, "Proc_Robo", 110, 60)
no("r_ref", "service", "Carregar território, paradas e leituras LDR", 345, 215, "Proc_Robo", 120, 60)
no("r_coleta", "service", "Coletar lote de relatos (data/inbox)", 490, 215, "Proc_Robo", 120, 60)
caixa("r_sub", "sub", "Processar cada relato do lote", 60, 290, 1850, 460, "Proc_Robo", mi=True)
no("r_sla", "service", "Monitorar SLA e escalonar vencidos", 1500, 215, "Proc_Robo", 120, 60, mi=True)
no("r_exp", "service", "Exportar JSON e GeoJSON para o MVP", 1640, 215, "Proc_Robo", 115, 60)
no("r_res", "service", "Registrar resumo e liberar trava", 1775, 215, "Proc_Robo", 110, 60)
no("r_fim", "end", "Execução concluída", 1880, 215, "Proc_Robo", rotulo="below")

# ---- Robô: subprocesso (por relato)
S = "Proc_Robo"
Y, UP, DN = 530, 395, 665
no("s_ini", "start", "Relato", 100, Y, S, pai="r_sub", rotulo="below")
no("s_ler", "service", "Ler JSON e validar schema", 185, Y, S, 100, 60, pai="r_sub")
no("s_err", "boundary_err", "", 175, 500, S, pai="r_sub", preso="s_ler")
no("s_q1", "end", "Quarentena (JSON/schema)", 175, UP, S, pai="r_sub", rotulo="above")
no("g_dup", "gw", "Já processado?", 285, Y, S, pai="r_sub", rotulo=(335, 478))
no("s_dup", "end", "Ignorado (idempotente)", 285, UP, S, pai="r_sub", rotulo="above")
no("s_qc", "end", "Quarentena (conflito_id)", 285, DN, S, pai="r_sub", rotulo="below")
no("s_reg", "service", "Validar território, datas e foto", 385, Y, S, 100, 60, pai="r_sub")
no("g_reg", "gw", "Regras OK?", 480, Y, S, pai="r_sub", rotulo=(512, 585))
no("s_q2", "end", "Quarentena (motivo)", 480, UP, S, pai="r_sub", rotulo="above")
no("s_lgpd", "service", "Anonimizar: EXIF, PII e hash do contato", 580, Y, S, 100, 60, pai="r_sub")
no("g_abu", "gw", "Contato > 5 relatos/h?", 680, Y, S, pai="r_sub", rotulo=(680, 478))
no("s_vis", "service", "Classificar iluminação (Visão ou fallback)", 780, Y, S, 100, 60, pai="r_sub")
no("g_conf", "gw", "Confiança ≥ 0,60?", 880, Y, S, pai="r_sub", rotulo=(880, 478))
no("s_rev", "end_msg", "Fila de revisão humana", 930, DN, S, pai="r_sub", rotulo=(866, 704))
no("g_adq", "gw", "Iluminação adequada?", 975, Y, S, pai="r_sub", rotulo=(975, 588))
no("s_imp", "end", "Improcedente (arquivado)", 975, UP, S, pai="r_sub", rotulo="above")
no("s_ldr", "service", "Cruzar com sensor LDR (40 m / 72 h)", 1075, Y, S, 100, 60, pai="r_sub")
no("g_ldr", "gw", "Sensor LDR contesta?", 1175, Y, S, pai="r_sub", rotulo=(1175, 478))
no("s_enr", "service", "Enriquecer: Open-Meteo, paradas e pontos sensíveis", 1275, Y, S, 108, 64, pai="r_sub")
no("g_prox", "gw", "Chamado aberto a ≤ 30 m?", 1380, Y, S, pai="r_sub", rotulo=(1440, 478))
no("s_mes", "service", "Mesclar no chamado (recorrência)", 1475, UP, S, 100, 56, pai="r_sub")
no("s_cri", "service", "Criar chamado (checa reincidência)", 1475, DN, S, 100, 56, pai="r_sub")
no("g_join", "gw", "", 1570, Y, S, pai="r_sub")
no("s_pri", "service", "Prioridade explicável + SLA; gravar em transação e auditar", 1665, Y, S, 112, 68, pai="r_sub")
no("g_p1", "gw", "Prioridade P1?", 1765, Y, S, pai="r_sub", rotulo=(1765, 478))
no("s_ale", "service", "Disparar alerta (arquivo, webhook, Telegram)", 1765, DN, S, 104, 60, pai="r_sub")
no("s_fim", "end", "Relato processado", 1860, Y, S, pai="r_sub", rotulo=(1846, 490))

# ---- Revisor
no("v_ini", "start_msg", "Relato em revisão", 930, 865, "Proc_Revisor", rotulo="below")
no("v_ana", "user", "Analisar foto e motivo no painel", 1085, 865, "Proc_Revisor", 110, 58)
no("v_gw", "gw", "Aprovado?", 1195, 865, "Proc_Revisor", rotulo=(1195, 926))
no("v_ree", "user", "Reenfileirar com rótulo humano", 1310, 830, "Proc_Revisor", 120, 48)
no("v_rej", "user", "Rejeitar: relato improcedente", 1310, 905, "Proc_Revisor", 120, 48)
no("v_fim1", "end", "Volta ao robô", 1420, 830, "Proc_Revisor", rotulo="right")
no("v_fim2", "end", "Encerrado", 1420, 905, "Proc_Revisor", rotulo="right")

# ---- Manutenção
no("m_ini", "start_msg", "Alerta P1 ou SLA vencido", 1430, 1025, "Proc_Manut", rotulo="below")
no("m_con", "user", "Consertar o ponto em campo", 1545, 1025, "Proc_Manut", 110, 50)
no("m_res", "user", "Marcar resolvido (PATCH /chamados)", 1690, 1025, "Proc_Manut", 130, 50)
no("m_fim", "end", "Chamado resolvido", 1810, 1025, "Proc_Manut", rotulo="below")

# ----------------------------------------------------------------- fluxos
F = []  # (id, origem, destino, nome, pontos, processo, pai, (label_x, label_y))


def fl(id_, a, b, pts=None, nome="", lbl=None):
    pts = pts or [R(a), L(b)]
    F.append(dict(id=id_, a=a, b=b, nome=nome, pts=pts, proc=N[a]["proc"], pai=N[a]["pai"] if N[a]["pai"] else None,
                  lbl=lbl))


fl("f1", "c_ini", "c_foto"); fl("f2", "c_foto", "c_app"); fl("f3", "c_app", "c_fim")  # noqa: E702
fl("f10", "r_ini", "r_trava"); fl("f11", "r_trava", "r_ref"); fl("f12", "r_ref", "r_coleta")  # noqa: E702
fl("f13", "r_coleta", "r_sub", [B("r_coleta"), (490, 290)])
fl("f14", "r_sub", "r_sla", [(1400, 290), (1400, 215), L("r_sla")])
fl("f15", "r_sla", "r_exp"); fl("f16", "r_exp", "r_res"); fl("f17", "r_res", "r_fim")  # noqa: E702

fl("s1", "s_ini", "s_ler")
fl("s2", "s_err", "s_q1", [T("s_err"), B("s_q1")], "inválido", (205, 455))
fl("s3", "s_ler", "g_dup")
fl("s4", "g_dup", "s_dup", [T("g_dup"), B("s_dup")], "sim, idêntico", (325, 440))
fl("s5", "g_dup", "s_qc", [B("g_dup"), T("s_qc")], "sim, conteúdo diferente", (345, 615))
fl("s6", "g_dup", "s_reg", nome="não", lbl=(318, 520))
fl("s7", "s_reg", "g_reg")
fl("s8", "g_reg", "s_q2", [T("g_reg"), B("s_q2")], "não", (497, 440))
fl("s9", "g_reg", "s_lgpd", nome="sim", lbl=(512, 520))
fl("s10", "s_lgpd", "g_abu")
fl("s11", "g_abu", "s_rev", [B("g_abu"), (680, DN), L("s_rev")], "sim", (695, 600))
fl("s12", "g_abu", "s_vis", nome="não", lbl=(712, 520))
fl("s13", "s_vis", "g_conf")
fl("s14", "g_conf", "s_rev", [B("g_conf"), (880, DN), L("s_rev")], "não", (895, 600))
fl("s15", "g_conf", "g_adq", nome="sim", lbl=(912, 520))
fl("s16", "g_adq", "s_imp", [T("g_adq"), B("s_imp")], "sim", (992, 440))
fl("s17", "g_adq", "s_ldr", nome="não", lbl=(1007, 520))
fl("s18", "s_ldr", "g_ldr")
fl("s19", "g_ldr", "s_rev", [B("g_ldr"), (1175, DN), R("s_rev")], "sim", (1190, 600))
fl("s20", "g_ldr", "s_enr", nome="não", lbl=(1207, 520))
fl("s21", "s_enr", "g_prox")
fl("s22", "g_prox", "s_mes", [T("g_prox"), (1380, UP), L("s_mes")], "sim", (1395, 440))
fl("s23", "g_prox", "s_cri", [B("g_prox"), (1380, DN), L("s_cri")], "não", (1395, 600))
fl("s24", "s_mes", "g_join", [R("s_mes"), (1570, UP), T("g_join")])
fl("s25", "s_cri", "g_join", [R("s_cri"), (1570, DN), B("g_join")])
fl("s26", "g_join", "s_pri")
fl("s27", "s_pri", "g_p1")
fl("s28", "g_p1", "s_fim", nome="não", lbl=(1805, 520))
fl("s29", "g_p1", "s_ale", [B("g_p1"), T("s_ale")], "sim", (1780, 600))
fl("s30", "s_ale", "s_fim", [R("s_ale"), (1860, DN), B("s_fim")])

fl("v1", "v_ini", "v_ana"); fl("v2", "v_ana", "v_gw")  # noqa: E702
fl("v3", "v_gw", "v_ree", [T("v_gw"), (1195, 830), L("v_ree")], "sim", (1225, 822))
fl("v4", "v_gw", "v_rej", [B("v_gw"), (1195, 905), L("v_rej")], "não", (1225, 897))
fl("v5", "v_ree", "v_fim1"); fl("v6", "v_rej", "v_fim2")  # noqa: E702
fl("m1", "m_ini", "m_con"); fl("m2", "m_con", "m_res"); fl("m3", "m_res", "m_fim")  # noqa: E702

MSG = [
    ("mf1", "c_app", "r_coleta", [B("c_app"), (370, 165), (490, 165), T("r_coleta")], "relato + foto", (430, 158)),
    ("mf2", "s_rev", "v_ini", [B("s_rev"), T("v_ini")], "", None),
    ("mf3", "v_ree", "Pool_Robo", [T("v_ree"), (1310, 770)], "novo JSON em data/inbox", (1385, 780)),
    ("mf4", "s_ale", "m_ini", [B("s_ale"), (1765, 985), (1430, 985), T("m_ini")], "alerta", (1600, 978)),
]

ANOT = [
    dict(id="a1", alvo="r_sub", x=640, y=186, w=660, h=62, proc="Proc_Robo", pai=None, pts=[(900, 248), (900, 290)],
         texto="Qualquer erro inesperado em um relato: o arquivo vai para data/erros (dead letter), gera log ERROR "
               "e auditoria, e o lote CONTINUA. Recuperação: python main.py reprocessar-erros"),
    dict(id="a2", alvo="s_enr", x=1040, y=340, w=300, h=76, proc="Proc_Robo", pai="r_sub", pts=[(1275, 416), (1275, 498)],
         texto="Open-Meteo: timeout 5 s, 3 tentativas com backoff exponencial e circuit breaker. "
               "Fora do ar? Usa horário fixo, marca clima_indisponivel e o relato segue."),
]


# ----------------------------------------------------------------- XML
def gerar_xml() -> str:
    tag = {"start": "startEvent", "start_timer": "startEvent", "start_msg": "startEvent", "end": "endEvent",
           "end_msg": "endEvent", "task": "task", "user": "userTask", "service": "serviceTask",
           "gw": "exclusiveGateway", "sub": "subProcess", "boundary_err": "boundaryEvent"}
    entradas = {i: [] for i in N}
    saidas = {i: [] for i in N}
    for f in F:
        saidas[f["a"]].append(f["id"])
        entradas[f["b"]].append(f["id"])

    def el(n, recuo):
        p = " " * recuo
        attrs = f'id="{n["id"]}" name={quoteattr(n["nome"])}'
        if n["kind"] == "boundary_err":
            attrs += f' attachedToRef="{n["preso"]}"'
        corpo = [f"{p}  <bpmn:incoming>{x}</bpmn:incoming>" for x in entradas[n["id"]]]
        corpo += [f"{p}  <bpmn:outgoing>{x}</bpmn:outgoing>" for x in saidas[n["id"]]]
        if n["kind"] == "start_timer":
            corpo.append(f'{p}  <bpmn:timerEventDefinition id="{n["id"]}_def"><bpmn:timeCycle>R/PT15M</bpmn:timeCycle>'
                         f"</bpmn:timerEventDefinition>")
        if n["kind"] in ("start_msg", "end_msg"):
            corpo.append(f'{p}  <bpmn:messageEventDefinition id="{n["id"]}_def" />')
        if n["kind"] == "boundary_err":
            corpo.append(f'{p}  <bpmn:errorEventDefinition id="{n["id"]}_def" />')
        if n["mi"]:
            corpo.append(f'{p}  <bpmn:multiInstanceLoopCharacteristics isSequential="true" />')
        if n["kind"] == "sub":
            for filho in [x for x in N.values() if x["pai"] == n["id"]]:
                corpo.append(el(filho, recuo + 2))
            for f in [x for x in F if x["pai"] == n["id"]]:
                corpo.append(fluxo(f, recuo + 2))
            for a in [x for x in ANOT if x["pai"] == n["id"]]:
                corpo.extend(anotacao(a, recuo + 2))
        return f"{p}<bpmn:{tag[n['kind']]} {attrs}>\n" + "\n".join(corpo) + f"\n{p}</bpmn:{tag[n['kind']]}>"

    def fluxo(f, recuo):
        return f'{" " * recuo}<bpmn:sequenceFlow id="{f["id"]}" name={quoteattr(f["nome"])} ' \
               f'sourceRef="{f["a"]}" targetRef="{f["b"]}" />'

    def anotacao(a, recuo):
        p = " " * recuo
        return [f'{p}<bpmn:textAnnotation id="{a["id"]}"><bpmn:text>{escape(a["texto"])}</bpmn:text></bpmn:textAnnotation>',
                f'{p}<bpmn:association id="{a["id"]}_as" sourceRef="{a["id"]}" targetRef="{a["alvo"]}" />']

    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
              'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
              'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
              'id="Defs_LuzSegura" targetNamespace="https://github.com/luz-segura/rpa" exporter="gerar_bpmn.py" '
              'exporterVersion="1.0">',
              '  <bpmn:collaboration id="Colab_LuzSegura">']
    for pid, proc, nome, *_ in POOLS:
        linhas.append(f'    <bpmn:participant id="{pid}" name={quoteattr(nome)} processRef="{proc}" />')
    for mid, a, b, _pts, nome, _l in MSG:
        linhas.append(f'    <bpmn:messageFlow id="{mid}" name={quoteattr(nome)} sourceRef="{a}" targetRef="{b}" />')
    linhas.append("  </bpmn:collaboration>")
    for _pid, proc, nome, *_ in POOLS:
        linhas.append(f'  <bpmn:process id="{proc}" name={quoteattr(nome)} isExecutable="false">')
        for n in [x for x in N.values() if x["proc"] == proc and not x["pai"]]:
            linhas.append(el(n, 4))
        for f in [x for x in F if x["proc"] == proc and not x["pai"]]:
            linhas.append(fluxo(f, 4))
        for a in [x for x in ANOT if x["proc"] == proc and not x["pai"]]:
            linhas.extend(anotacao(a, 4))
        linhas.append("  </bpmn:process>")

    # ---- DI
    linhas.append('  <bpmndi:BPMNDiagram id="Diag_LuzSegura"><bpmndi:BPMNPlane id="Plano" bpmnElement="Colab_LuzSegura">')
    for pid, _p, _n, x, y, w, h in POOLS:
        linhas.append(f'    <bpmndi:BPMNShape id="{pid}_di" bpmnElement="{pid}" isHorizontal="true">'
                      f'<dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" /></bpmndi:BPMNShape>')
    for n in N.values():
        extra = ' isExpanded="true"' if n["kind"] == "sub" else ""
        rot = ""
        lx = _rotulo_xy(n)
        if lx:
            rot = f'<bpmndi:BPMNLabel><dc:Bounds x="{lx[0] - 50:.0f}" y="{lx[1] - 12:.0f}" width="100" height="27" />' \
                  f"</bpmndi:BPMNLabel>"
        linhas.append(f'    <bpmndi:BPMNShape id="{n["id"]}_di" bpmnElement="{n["id"]}"{extra}>'
                      f'<dc:Bounds x="{n["x"]:.0f}" y="{n["y"]:.0f}" width="{n["w"]:.0f}" height="{n["h"]:.0f}" />'
                      f"{rot}</bpmndi:BPMNShape>")
    for a in ANOT:
        linhas.append(f'    <bpmndi:BPMNShape id="{a["id"]}_di" bpmnElement="{a["id"]}">'
                      f'<dc:Bounds x="{a["x"]}" y="{a["y"]}" width="{a["w"]}" height="{a["h"]}" /></bpmndi:BPMNShape>')
        linhas.append(f'    <bpmndi:BPMNEdge id="{a["id"]}_as_di" bpmnElement="{a["id"]}_as">' +
                      "".join(f'<di:waypoint x="{x:.0f}" y="{y:.0f}" />' for x, y in a["pts"]) + "</bpmndi:BPMNEdge>")
    for f in F:
        rot = ""
        if f["nome"] and f["lbl"]:
            rot = f'<bpmndi:BPMNLabel><dc:Bounds x="{f["lbl"][0] - 30:.0f}" y="{f["lbl"][1] - 8:.0f}" ' \
                  f'width="70" height="14" /></bpmndi:BPMNLabel>'
        linhas.append(f'    <bpmndi:BPMNEdge id="{f["id"]}_di" bpmnElement="{f["id"]}">' +
                      "".join(f'<di:waypoint x="{x:.0f}" y="{y:.0f}" />' for x, y in f["pts"]) + rot + "</bpmndi:BPMNEdge>")
    for mid, _a, _b, pts, nome, lbl in MSG:
        rot = f'<bpmndi:BPMNLabel><dc:Bounds x="{lbl[0] - 60:.0f}" y="{lbl[1] - 8:.0f}" width="130" height="14" />' \
              f"</bpmndi:BPMNLabel>" if lbl else ""
        linhas.append(f'    <bpmndi:BPMNEdge id="{mid}_di" bpmnElement="{mid}">' +
                      "".join(f'<di:waypoint x="{x:.0f}" y="{y:.0f}" />' for x, y in pts) + rot + "</bpmndi:BPMNEdge>")
    linhas.append("  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>")
    linhas.append("</bpmn:definitions>")
    return "\n".join(linhas) + "\n"


def _rotulo_xy(n):
    r = n["rotulo"]
    if not r or not n["nome"]:
        return None
    if isinstance(r, tuple):
        return r
    if r == "below":
        return (n["cx"], n["y"] + n["h"] + 16)
    if r == "above":
        return (n["cx"], n["y"] - 18)
    if r == "right":
        return (n["x"] + n["w"] + 40, n["cy"])
    return None


# ----------------------------------------------------------------- PNG
COR = {"linha": "#1f2937", "task": "#ffffff", "sub": "#f8fafc", "pool": "#ffffff", "faixa": "#e5e7eb",
       "ini": "#dcfce7", "fim": "#fee2e2", "gw": "#fef9c3", "msg": "#6b7280", "anot": "#374151", "rev": "#e0e7ff"}
PX = 0.72  # 1 px do diagrama em pontos tipográficos (figura em 100 dpi)


def _texto(ax, x, y, txt, largura_px, tam=10, peso="normal", cor=None, ha="center", va="center"):
    chars = max(8, int(largura_px / (tam * 0.56)))
    ax.text(x, y, "\n".join(textwrap.wrap(txt, chars)), ha=ha, va=va, fontsize=tam * PX, weight=peso,
            color=cor or COR["linha"], linespacing=1.15, family="DejaVu Sans", zorder=7)


def _seta(ax, pts, tracejado=False, cor=None):
    cor = cor or COR["linha"]
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=cor, lw=1.3 * PX * 1.4, ls=(0, (5, 3)) if tracejado else "-", solid_capstyle="butt", zorder=2)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    tam = 9
    p1 = (x1 - tam * math.cos(ang - 0.4), y1 - tam * math.sin(ang - 0.4))
    p2 = (x1 - tam * math.cos(ang + 0.4), y1 - tam * math.sin(ang + 0.4))
    ax.add_patch(Polygon([(x1, y1), p1, p2], closed=True, fc="white" if tracejado else cor, ec=cor,
                         lw=1.2 * PX, zorder=3))
    if tracejado:
        ax.add_patch(Circle(pts[0], 3.5, fc="white", ec=cor, lw=1.2 * PX, zorder=3))


def _evento(ax, n):
    r = n["w"] / 2
    fim = n["kind"].startswith("end")
    fundo = COR["fim"] if fim else COR["ini"]
    if n["kind"] == "boundary_err":
        fundo = "#ffffff"
    ax.add_patch(Circle((n["cx"], n["cy"]), r, fc=fundo, ec=COR["linha"], lw=(3.2 if fim else 1.4) * PX, zorder=4))
    if n["kind"] == "boundary_err":
        ax.add_patch(Circle((n["cx"], n["cy"]), r - 3, fc="none", ec=COR["linha"], lw=1 * PX, zorder=5))
        cx, cy = n["cx"], n["cy"]
        raio = [(cx - 5, cy + 6), (cx - 1, cy - 6), (cx + 1, cy + 1), (cx + 5, cy - 6), (cx + 1, cy + 6), (cx - 1, cy - 1)]
        ax.add_patch(Polygon(raio, closed=True, fc="white", ec=COR["linha"], lw=1 * PX, zorder=6))
    if n["kind"] == "start_timer":
        ax.add_patch(Circle((n["cx"], n["cy"]), r - 4, fc="white", ec=COR["linha"], lw=1 * PX, zorder=5))
        ax.plot([n["cx"], n["cx"]], [n["cy"], n["cy"] - 8], color=COR["linha"], lw=1.2 * PX, zorder=6)
        ax.plot([n["cx"], n["cx"] + 6], [n["cy"], n["cy"]], color=COR["linha"], lw=1.2 * PX, zorder=6)
    if n["kind"] in ("start_msg", "end_msg"):
        cheio = n["kind"] == "end_msg"
        x0, y0 = n["cx"] - 8, n["cy"] - 5.5
        ax.add_patch(Rectangle((x0, y0), 16, 11, fc=COR["linha"] if cheio else "white", ec=COR["linha"],
                               lw=1 * PX, zorder=6))
        ax.plot([x0, n["cx"], x0 + 16], [y0, n["cy"] + 1, y0], color="white" if cheio else COR["linha"],
                lw=1 * PX, zorder=7)
    pos = _rotulo_xy(n)
    if pos:
        _texto(ax, pos[0], pos[1], n["nome"], 110, tam=9.5, ha="center")


def _gateway(ax, n):
    cx, cy, r = n["cx"], n["cy"], n["w"] / 2
    ax.add_patch(Polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], closed=True, fc=COR["gw"],
                         ec=COR["linha"], lw=1.4 * PX, zorder=4))
    d = 8
    ax.plot([cx - d, cx + d], [cy - d, cy + d], color=COR["linha"], lw=2.2 * PX, zorder=5)
    ax.plot([cx - d, cx + d], [cy + d, cy - d], color=COR["linha"], lw=2.2 * PX, zorder=5)
    pos = _rotulo_xy(n)
    if pos:
        _texto(ax, pos[0], pos[1], n["nome"], 100, tam=9.5, peso="bold")


def _marcador_mi(ax, cx, base):
    for i in range(3):
        ax.plot([cx - 7, cx + 7], [base - 4 - 4 * i, base - 4 - 4 * i], color=COR["linha"], lw=1.6 * PX, zorder=6)


def _tarefa(ax, n):
    fundo = COR["task"]
    ax.add_patch(FancyBboxPatch((n["x"], n["y"]), n["w"], n["h"], boxstyle="round,pad=0,rounding_size=9",
                                fc=fundo, ec=COR["linha"], lw=1.4 * PX, zorder=4))
    # ícone de tipo no canto: engrenagem (serviço) ou pessoa (usuário)
    ix, iy = n["x"] + 9, n["y"] + 9
    if n["kind"] == "service":
        ax.add_patch(Circle((ix, iy), 4.2, fc="white", ec=COR["linha"], lw=1 * PX, zorder=5))
        ax.add_patch(Circle((ix, iy), 1.6, fc=COR["linha"], ec=COR["linha"], lw=0.5 * PX, zorder=6))
    elif n["kind"] == "user":
        ax.add_patch(Circle((ix, iy - 2), 2.6, fc="white", ec=COR["linha"], lw=1 * PX, zorder=5))
        ax.add_patch(FancyBboxPatch((ix - 4.5, iy + 1.2), 9, 4.5, boxstyle="round,pad=0,rounding_size=2",
                                    fc="white", ec=COR["linha"], lw=1 * PX, zorder=5))
    _texto(ax, n["cx"], n["cy"] + 2, n["nome"], n["w"] - 10, tam=9.5)
    if n["mi"]:
        _marcador_mi(ax, n["cx"], n["y"] + n["h"])


def renderizar(destino: Path) -> None:
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    for pid, _p, nome, x, y, w, h in POOLS:
        ax.add_patch(Rectangle((x, y), w, h, fc=COR["pool"], ec=COR["linha"], lw=1.4 * PX, zorder=1))
        ax.add_patch(Rectangle((x, y), 30, h, fc=COR["faixa"], ec=COR["linha"], lw=1.4 * PX, zorder=1))
        ax.text(x + 15, y + h / 2, nome, rotation=90, ha="center", va="center", fontsize=10.5 * PX * 1.1,
                weight="bold", color=COR["linha"], family="DejaVu Sans")

    sub = N["r_sub"]
    ax.add_patch(FancyBboxPatch((sub["x"], sub["y"]), sub["w"], sub["h"], boxstyle="round,pad=0,rounding_size=14",
                                fc=COR["sub"], ec=COR["linha"], lw=1.6 * PX, zorder=1.5))
    ax.text(sub["x"] + 14, sub["y"] + 14, "SUBPROCESSO: " + sub["nome"].upper() +
            "   (multi-instância sequencial = estrutura de repetição sobre a coleção de relatos)",
            ha="left", va="center", fontsize=10 * PX, weight="bold", color=COR["linha"], family="DejaVu Sans")
    _marcador_mi(ax, sub["cx"], sub["y"] + sub["h"])

    for a in ANOT:
        x, y, w, h = a["x"], a["y"], a["w"], a["h"]
        ax.plot([x + 10, x, x, x + 10], [y, y, y + h, y + h], color=COR["anot"], lw=1.2 * PX, zorder=3)
        _texto(ax, x + 10, y + h / 2, a["texto"], w - 16, tam=9.3, ha="left", cor=COR["anot"])
        xs, ys = zip(*a["pts"])
        ax.plot(xs, ys, color=COR["anot"], lw=1.2 * PX, ls=(0, (1.5, 2.5)), zorder=3)

    for f in F:
        _seta(ax, f["pts"])
        if f["nome"] and f["lbl"]:
            ax.text(f["lbl"][0], f["lbl"][1], f["nome"], ha="center", va="center", fontsize=9 * PX,
                    color="#374151", weight="bold",
                    family="DejaVu Sans", zorder=8,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    for _mid, _a, _b, pts, nome, lbl in MSG:
        _seta(ax, pts, tracejado=True, cor=COR["msg"])
        if nome and lbl:
            ax.text(lbl[0], lbl[1], nome, ha="center", va="center", fontsize=9 * PX, style="italic",
                    color=COR["msg"], family="DejaVu Sans", zorder=8,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))

    for n in N.values():
        if n["kind"] == "sub":
            continue
        if n["kind"] == "gw":
            _gateway(ax, n)
        elif n["kind"] in ("task", "user", "service"):
            _tarefa(ax, n)
        else:
            _evento(ax, n)

    ax.text(W - 20, H - 8, "Luz Segura · Robô RPA · BPMN 2.0 (docs/processo_luzsegura.bpmn)", ha="right",
            va="bottom", fontsize=8.5 * PX, color="#6b7280", family="DejaVu Sans")
    fig.savefig(destino, dpi=220, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    xml = gerar_xml()
    (DOCS / "processo_luzsegura.bpmn").write_text(xml, encoding="utf-8")
    renderizar(DOCS / "fluxo_bpmn.png")
    # recorte ampliado do subprocesso para o relatório
    from PIL import Image
    with Image.open(DOCS / "fluxo_bpmn.png") as img:
        k = img.width / W
        sub = N["r_sub"]
        img.crop((int((sub["x"] - 10) * k), int((sub["y"] - 10) * k), int((sub["x"] + sub["w"] + 10) * k),
                  int((sub["y"] + sub["h"] + 10) * k))).save(DOCS / "fluxo_bpmn_subprocesso.png")
        img.crop((0, 0, int(W * k), int(290 * k))).save(DOCS / "fluxo_bpmn_macro.png")
    print("BPMN e PNGs gerados em docs/")
