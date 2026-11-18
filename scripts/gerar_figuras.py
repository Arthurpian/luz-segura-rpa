"""Gera as figuras de documentação: arquitetura (Graphviz) e mapa dos chamados (matplotlib).

    python scripts/gerar_figuras.py          # depois de: python main.py seed && python main.py run
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from luzsegura_rpa.geo import carregar_pontos  # noqa: E402

DOT = r'''
digraph G {
  graph [rankdir=LR, fontname="DejaVu Sans", fontsize=13, nodesep=0.35, ranksep=0.7, bgcolor="white", pad=0.3,
         label="Luz Segura · onde o robô RPA se encaixa no MVP", labelloc=t, fontcolor="#111827"];
  node  [shape=box, style="rounded,filled", fontname="DejaVu Sans", fontsize=11, color="#1f2937", fillcolor="#ffffff", penwidth=1.3];
  edge  [fontname="DejaVu Sans", fontsize=9.5, color="#374151", fontcolor="#374151", penwidth=1.2];

  subgraph cluster_entrada { label="Entradas"; style="rounded,dashed"; color="#9ca3af"; fontcolor="#374151";
    app   [label="App do cidadão\n(foto + localização)"];
    ldr   [label="Estação LDR\n(Maker Lab)\nleituras_ldr.csv"];
    gtfs  [label="Paradas e pontos\nsensíveis (GTFS)"];
    terr  [label="Território do piloto\n(GeoJSON)"];
  }
  subgraph cluster_ext { label="Serviços externos"; style="rounded,dashed"; color="#9ca3af"; fontcolor="#374151";
    vis   [label="Visão Computacional\n(componente CV)\nou fallback local"];
    meteo [label="Open-Meteo\n(sem chave)"];
  }
  api   [label="API FastAPI\n/relatos  /chamados  /revisao\n/indicadores  /robo/executar", fillcolor="#e0e7ff"];
  inbox [label="data/inbox\n(fila de arquivos)", shape=folder, fillcolor="#f3f4f6"];
  robo  [label="ROBÔ RPA (Python)\nvalida · anonimiza · classifica\ndeduplica · prioriza · SLA\nretry · circuit breaker · dead letter", fillcolor="#fef3c7", penwidth=2.2, fontsize=12];

  subgraph cluster_saida { label="Saídas consumidas pelo MVP"; style="rounded,dashed"; color="#9ca3af"; fontcolor="#374151";
    db    [label="SQLite luzsegura.db\nchamados · relatos · fila_revisao\nexecucoes · auditoria", shape=cylinder, fillcolor="#dcfce7"];
    json  [label="chamados.json\nchamados.geojson", shape=note, fillcolor="#dcfce7"];
    alert [label="Alertas\narquivo · webhook · Telegram", shape=note, fillcolor="#fee2e2"];
    logs  [label="Logs JSONL\n(sem dados pessoais)", shape=note, fillcolor="#f3f4f6"];
  }
  subgraph cluster_mvp { label="Outros componentes da CitizenTech"; style="rounded"; color="#6366f1"; fontcolor="#3730a3";
    painel [label="Painel / MVP web\n(mapa + fila priorizada)"];
    rag    [label="Assistente RAG (GenAI)\n\"por que este ponto\nestá em primeiro?\""];
    bigd   [label="Pipeline Big Data\n(Airflow · Bronze)"];
    bi     [label="BI & Startup\n(indicadores de impacto)"];
  }
  rev   [label="Revisor humano", shape=box, style="rounded,filled", fillcolor="#ede9fe"];
  manut [label="Equipe de manutenção", shape=box, style="rounded,filled", fillcolor="#ede9fe"];

  app -> api [label="POST /relatos"];
  api -> inbox [label="JSON + foto"];
  inbox -> robo [label="lote a cada 15 min"];
  ldr -> robo; gtfs -> robo; terr -> robo;
  vis -> robo [label="rótulo + confiança", dir=both];
  meteo -> robo [label="nuvens, visibilidade,\npôr do sol"];
  robo -> db [label="transação"];
  robo -> json [label="escrita atômica"];
  robo -> alert [label="P1 / SLA"];
  robo -> logs;
  db -> api [label="leitura"];
  api -> painel; api -> rag [label="fatores da\nprioridade"];
  json -> bigd; json -> painel [style=dashed]; db -> bi [label="KPIs"];
  alert -> manut; manut -> api [label="PATCH resolvido"];
  rev -> api [label="aprovar / rejeitar"];
  api -> rev [label="fila de revisão", style=dashed];
}
'''


def arquitetura(destino: Path) -> None:
    subprocess.run(["dot", "-Tpng", "-Gdpi=170", "-o", str(destino)], input=DOT.encode(), check=True)


def mapa(destino: Path) -> None:
    geo = json.loads((RAIZ / "data/saida/chamados.geojson").read_text(encoding="utf-8"))
    terr = json.loads((RAIZ / "data/referencia/territorio.geojson").read_text(encoding="utf-8"))
    pontos, _ = carregar_pontos(RAIZ / "data/referencia/pontos_referencia.csv")
    cores = {"P1": "#dc2626", "P2": "#ea580c", "P3": "#ca8a04", "P4": "#64748b"}
    fig, ax = plt.subplots(figsize=(9, 8), dpi=160)
    anel = terr["features"][0]["geometry"]["coordinates"][0]
    ax.fill([p[0] for p in anel], [p[1] for p in anel], color="#fef9c3", alpha=0.35, zorder=0)
    ax.plot([p[0] for p in anel], [p[1] for p in anel], color="#a16207", lw=1.2, ls="--", zorder=1)
    for p in pontos:
        marcador = "s" if p.tipo == "parada_onibus" else "^"
        ax.scatter(p.lon, p.lat, marker=marcador, s=40, c="#1e3a8a" if p.tipo == "parada_onibus" else "#0e7490",
                   zorder=2, edgecolors="white", linewidths=0.6)
        ax.annotate(p.id, (p.lon, p.lat), textcoords="offset points", xytext=(5, -10), fontsize=6, color="#64748b")
    for f in geo["features"]:
        lon, lat = f["geometry"]["coordinates"]
        pr = f["properties"]
        cor = "#16a34a" if pr["status"] == "resolvido" else cores[pr["prioridade"]]
        ax.scatter(lon, lat, s=70 + 35 * pr["qtd_relatos"], c=cor, edgecolors="black", linewidths=0.8, zorder=4)
        if pr["status"] == "resolvido":
            ax.annotate(f'{pr["id"]} (resolvido)', (lon, lat), textcoords="offset points", xytext=(-10, -16),
                        fontsize=7, color="#15803d", ha="right", zorder=5)
            continue
        if pr["prioridade"] == "P4":
            continue  # legenda explica; evita poluir a linha de P4
        rotulo = f'{pr["id"]} · {pr["prioridade"]} ({pr["score"]})' + (" · SLA vencido" if pr["atrasado"] else "") \
            + (f' · {pr["qtd_relatos"]} relatos' if pr["qtd_relatos"] > 1 else "")
        ax.annotate(rotulo, (lon, lat), textcoords="offset points", xytext=(9, 6), fontsize=7.3, weight="bold",
                    zorder=5, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8))
    for pr, cor in cores.items():
        ax.scatter([], [], c=cor, s=70, edgecolors="black", label=f"Chamado {pr}")
    ax.scatter([], [], c="#16a34a", s=70, edgecolors="black", label="Resolvido")
    ax.scatter([], [], c="white", s=0, label="Tamanho do círculo = nº de relatos")
    ax.scatter([], [], marker="s", c="#1e3a8a", s=40, label="Parada de ônibus")
    ax.scatter([], [], marker="^", c="#0e7490", s=40, label="Escola, UBS, estação, praça")
    ax.legend(loc="lower left", fontsize=8, frameon=True)
    ax.set_title("Chamados gerados pelo robô (território simulado no Centro de Osasco)", fontsize=11)
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")  # noqa: E702
    ax.set_aspect(1 / 0.917)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(destino)
    plt.close(fig)


if __name__ == "__main__":
    (RAIZ / "docs").mkdir(exist_ok=True)
    (RAIZ / "assets").mkdir(exist_ok=True)
    arquitetura(RAIZ / "docs/arquitetura.png")
    if (RAIZ / "data/saida/chamados.geojson").exists():
        mapa(RAIZ / "assets/mapa_chamados.png")
    print("figuras geradas")
