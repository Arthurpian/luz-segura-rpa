"""Ponto de entrada: python main.py <comando>  (seed | run | api | status | reprocessar-erros)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from luzsegura_rpa.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
