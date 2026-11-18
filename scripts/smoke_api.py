"""Sobe a API de verdade (uvicorn) por alguns segundos e chama as rotas principais.

    python scripts/smoke_api.py
"""
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402

from luzsegura_rpa.api import criar_app  # noqa: E402
from luzsegura_rpa.config import Config  # noqa: E402

PORTA = 8765
servidor = uvicorn.Server(uvicorn.Config(criar_app(Config.carregar()), host="127.0.0.1", port=PORTA,
                                         log_level="warning"))
threading.Thread(target=servidor.run, daemon=True).start()
for _ in range(100):
    if servidor.started:
        break
    time.sleep(0.1)

falhas = 0
for rota in ["/", "/health", "/chamados", "/indicadores", "/revisao", "/execucoes", "/referencias",
             "/docs", "/static/vendor/leaflet/leaflet.js"]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA}{rota}", timeout=10) as r:
            print(f"  {r.status}  GET {rota}")
    except urllib.error.HTTPError as erro:
        falhas += 1
        print(f"  {erro.code}  GET {rota}  <-- FALHOU")
    except Exception as erro:  # noqa: BLE001
        falhas += 1
        print(f"  ERRO GET {rota}: {erro}")
servidor.should_exit = True
time.sleep(0.5)
print("API OK" if falhas == 0 else f"API com {falhas} falha(s)")
sys.exit(1 if falhas else 0)
