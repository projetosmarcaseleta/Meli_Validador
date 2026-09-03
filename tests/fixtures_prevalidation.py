"""Fixtures de metadados e URLs de imagem para o Autoharness de pré-validação."""

PRODUCT_A_IMG = "https://httpbin.org/image/jpeg"
PRODUCT_B_IMG = "https://httpbin.org/image/png"


def _side(titulo, ean, cor, voltagem, image_url, mlb="MLB000"):
    return {
        "mlb": mlb,
        "titulo": titulo,
        "ean": ean,
        "cor": cor,
        "voltagem": voltagem,
        "image_urls": [image_url],
    }


def scenario_a_perfect_match() -> dict:
    titulo = "Air Fryer X 4L"
    ean = "7891234567890"
    cor = "Preto"
    voltagem = "110V"
    return {
        "sku": "237274700",
        "catalogo": _side(titulo, ean, cor, voltagem, PRODUCT_A_IMG, "MLB111"),
        "tradicional": _side(titulo, ean, cor, voltagem, PRODUCT_A_IMG, "MLB222"),
    }


def scenario_b_metadata_mismatch() -> dict:
    titulo = "Air Fryer X 4L"
    ean = "7891234567890"
    return {
        "sku": "237274701",
        "catalogo": _side(titulo, ean, "Branco", "110V", PRODUCT_A_IMG, "MLB111"),
        "tradicional": _side(titulo, ean, "Preto", "220V", PRODUCT_A_IMG, "MLB222"),
    }


def scenario_c_visual_mismatch() -> dict:
    titulo = "Air Fryer X 4L"
    ean = "7891234567890"
    cor = "Preto"
    voltagem = "110V"
    return {
        "sku": "237274702",
        "catalogo": _side(titulo, ean, cor, voltagem, PRODUCT_A_IMG, "MLB111"),
        "tradicional": _side(titulo, ean, cor, voltagem, PRODUCT_B_IMG, "MLB222"),
    }
