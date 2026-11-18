"""Linha de comando do robô.

    python main.py seed                 gera dados simulados (limpa o ambiente)
    python main.py run                  executa o robô uma vez
    python main.py run --loop 15        executa a cada 15 minutos (agendador simples)
    python main.py api                  sobe a API + painel em http://127.0.0.1:8000
    python main.py status               mostra os indicadores
    python main.py reprocessar-erros    devolve a dead letter para a caixa de entrada
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .banco import Repositorio
from .config import Config
from .logs import configurar_logs, fechar_logs
from .resiliencia import ExecucaoConcorrente
from .robo import Robo, reprocessar_erros


def _tabela_resumo(r) -> str:
    linhas = [
        ("Relatos lidos", r.lidos), ("Chamados criados", r.chamados_criados), ("Mesclados (dedupe)", r.mesclados),
        ("Improcedentes", r.improcedentes), ("Revisão humana", r.revisao_humana), ("Quarentena", r.quarentena),
        ("Duplicados ignorados", r.duplicados_ignorados), ("Erros (dead letter)", r.erros),
        ("Alertas enviados", r.alertas), ("Escalonados por SLA", r.escalados_sla),
        ("Clima em fallback", r.clima_degradado), ("Duração (s)", r.duracao_s),
    ]
    largura = max(len(n) for n, _ in linhas)
    corpo = "\n".join(f"  {n:<{largura}}  {v}" for n, v in linhas)
    return f"\n=== RESUMO {r.run_id} ({r.status}) ===\n{corpo}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="luzsegura-rpa", description="Robô RPA Luz Segura")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_seed = sub.add_parser("seed", help="gera dados simulados")
    p_seed.add_argument("--manter", action="store_true", help="não apaga banco e pastas antes")
    p_run = sub.add_parser("run", help="executa o robô")
    p_run.add_argument("--loop", type=float, metavar="MIN", help="repete a cada MIN minutos")
    p_api = sub.add_parser("api", help="sobe a API e o painel")
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--port", type=int, default=8000)
    sub.add_parser("status", help="indicadores")
    sub.add_parser("reprocessar-erros", help="reenfileira a dead letter")
    args = parser.parse_args(argv)

    cfg = Config.carregar()
    cfg.garantir_pastas()
    configurar_logs(cfg)

    if args.comando == "seed":
        from .dados_simulados import gerar_cenarios
        fechar_logs()  # no Windows, o arquivo de log aberto não pode ser apagado pelo seed
        cenarios = gerar_cenarios(cfg, limpar=not args.manter)
        configurar_logs(cfg)  # o seed recria a pasta de logs
        print(f"\n{len(cenarios)} cenários gerados em data/inbox (+ histórico no banco):\n")
        for c in cenarios:
            print(f"  {c['codigo']}  [{c['tipo']:<7}] {c['titulo']:<58} -> {c['esperado']}")
        print("\nAgora rode:  python main.py run")
        return 0

    if args.comando == "run":
        while True:
            try:
                resumo = Robo(cfg).executar()
                print(_tabela_resumo(resumo))
            except ExecucaoConcorrente as erro:
                print(f"Execução ignorada: {erro}")
                if not args.loop:
                    return 2
            if not args.loop:
                return 0 if resumo.status != "falhou" else 1
            print(f"Próxima execução em {args.loop:g} min (Ctrl+C para sair)")
            try:
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                return 0

    if args.comando == "api":
        import uvicorn
        from .api import criar_app
        print(f"Painel: http://{args.host}:{args.port}   Documentação da API: http://{args.host}:{args.port}/docs")
        uvicorn.run(criar_app(cfg), host=args.host, port=args.port, log_level="warning")
        return 0

    if args.comando == "status":
        repo = Repositorio(cfg.db_path)
        print(json.dumps(repo.indicadores(cfg.minutos_manuais_por_relato), ensure_ascii=False, indent=2))
        return 0

    if args.comando == "reprocessar-erros":
        print(f"{reprocessar_erros(cfg)} relato(s) devolvido(s) para data/inbox")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
