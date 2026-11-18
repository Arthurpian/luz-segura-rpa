"""Proteção de dados pessoais (LGPD by design).

- Pseudonimização do contato (hash com salt): o robô consegue detectar abuso
  sem guardar e-mail ou telefone.
- Mascaramento de e-mail, telefone, CPF e placa em textos livres e logs.
- Remoção de metadados EXIF das fotos (GPS do aparelho, modelo do celular).
- Arredondamento de coordenadas em logs (~110 m).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import Image, ImageOps

RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
# lookbehind/lookahead evitam mascarar IDs como LS-20261117-0001
RE_TELEFONE = re.compile(r"(?<![\w-])(?:\+?55[\s-]?)?(?:\(?\d{2}\)?[\s-]?)?9?\d{4}[\s-]?\d{4}(?![\w-])")
RE_PLACA = re.compile(r"\b[A-Z]{3}-?\d[A-Z0-9]\d{2}\b", re.IGNORECASE)

MASCARA = "[removido-LGPD]"


def mascarar_texto(texto: str | None) -> str | None:
    """Remove dados pessoais de texto livre (descrições e mensagens de log)."""
    if not texto:
        return texto
    texto = RE_EMAIL.sub(MASCARA, texto)
    texto = RE_CPF.sub(MASCARA, texto)
    texto = RE_TELEFONE.sub(MASCARA, texto)
    texto = RE_PLACA.sub(MASCARA, texto)
    return texto


def pseudonimizar(valor: str | None, salt: str) -> str | None:
    """Hash irreversível do contato. Mesmo contato -> mesmo hash."""
    if not valor:
        return None
    normalizado = re.sub(r"[\s()\-.]", "", valor.strip().lower())
    return hashlib.sha256(f"{salt}:{normalizado}".encode()).hexdigest()[:16]


def arredondar(coordenada: float, casas: int = 3) -> float:
    return round(coordenada, casas)


def higienizar_foto(origem: Path, destino: Path, lado_max: int = 1280) -> dict:
    """Recria a imagem só com os pixels (sem EXIF/GPS) e reduz o tamanho.

    Foto leve também ajuda quem usa celular de entrada e internet ruim.
    """
    with Image.open(origem) as img:
        tinha_exif = bool(img.getexif())
        img = ImageOps.exif_transpose(img)  # preserva a orientação antes de descartar o EXIF
        img = img.convert("RGB")
        img.thumbnail((lado_max, lado_max))
        limpa = Image.frombytes(img.mode, img.size, img.tobytes())
    destino.parent.mkdir(parents=True, exist_ok=True)
    limpa.save(destino, format="JPEG", quality=85, optimize=True)
    return {
        "largura": limpa.width,
        "altura": limpa.height,
        "exif_removido": tinha_exif,
        "bytes": destino.stat().st_size,
    }
