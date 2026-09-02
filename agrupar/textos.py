from __future__ import annotations

import re
import unicodedata
from datetime import datetime


_RUIDO_QUASE_FAMILIA = re.compile(
    r"\b(?:masculino|feminino|unissex|unisex|sem genero|confortavel)\b"
)


def normalizar_texto(valor: object) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    texto = re.sub(r"\s+", " ", texto)
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    return texto.casefold()


def chave_quase_familia(valor: object) -> str:
    """Nome de família sem gênero/Confortável — para achar split só de texto."""
    texto = _RUIDO_QUASE_FAMILIA.sub(" ", normalizar_texto(valor))
    return re.sub(r"\s+", " ", texto).strip()


def timestamp(valor: object) -> float:
    if not valor:
        return 0.0
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
