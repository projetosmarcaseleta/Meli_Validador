from __future__ import annotations

import re

from agrupar.textos import normalizar_texto

GENEROS_VALIDOS = ("Masculino", "Feminino", "Unissex")


def detectar_genero(*fontes: object) -> str:
    """Gênero sai só do texto de transmissão/título, como no n8n."""
    bloco = " ".join(normalizar_texto(fonte).upper() for fonte in fontes if fonte)
    if re.search(r"\bUNISSEX\b|\bUNISEX\b", bloco):
        return "Unissex"
    if re.search(r"\bMASCULIN[OA]\b", bloco):
        return "Masculino"
    if re.search(r"\bFEMININ[OA]\b", bloco):
        return "Feminino"
    return "NaoIdentificado"
