"""Renderiza a saída de um comando como imagem de terminal (evidência para o relatório).

    python scripts/terminal_png.py saida.txt assets/imagem.png "titulo da janela"
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTE = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
CORES = {"ERROR": (255, 110, 110), "CRITICAL": (255, 80, 80), "WARNING": (255, 196, 92), "INFO": (190, 230, 255),
         "PASSED": (120, 220, 140), "FAILED": (255, 110, 110), "===": (255, 213, 74), "S0": (200, 200, 200)}


def renderizar(texto: str, destino: Path, titulo: str, largura_max: int = 150) -> None:
    linhas = []
    for linha in texto.rstrip().splitlines():
        while len(linha) > largura_max:
            linhas.append(linha[:largura_max]); linha = "   " + linha[largura_max:]  # noqa: E702
        linhas.append(linha)
    fonte = ImageFont.truetype(FONTE, 26)
    alt_linha, margem, barra = 34, 28, 54
    largura = int(max(fonte.getlength(l) for l in linhas + [titulo])) + 2 * margem
    altura = barra + margem + alt_linha * len(linhas) + margem
    img = Image.new("RGB", (max(largura, 1200), altura), (17, 24, 39))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, barra], fill=(31, 41, 55))
    for i, cor in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([20 + i * 30, 17, 40 + i * 30, 37], fill=cor)
    d.text((120, 12), titulo, font=fonte, fill=(156, 163, 175))
    y = barra + margem
    for l in linhas:
        cor = (229, 231, 235)
        for chave, c in CORES.items():
            if chave in l:
                cor = c
                break
        d.text((margem, y), l, font=fonte, fill=cor)
        y += alt_linha
    img.save(destino)


if __name__ == "__main__":
    renderizar(Path(sys.argv[1]).read_text(encoding="utf-8"), Path(sys.argv[2]), sys.argv[3])
