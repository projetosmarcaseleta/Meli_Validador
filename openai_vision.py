"""
openai_vision.py – Cliente GPT-4o (Structured Outputs) para pré-validação visual.
Não persiste dados; não escreve planilha. Fail-closed em qualquer falha de API/JSON.
"""

from __future__ import annotations

import json
import re
from typing import Callable

import requests

from config import (
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    OPENAI_MAX_IMAGES_PER_SIDE,
    OPENAI_TIMEOUT_SECONDS,
    OPENAI_VISION_MODEL,
)
from prevalidation import (
    PrevalidationError,
    compute_metadata_flags,
    empty_visual,
    merge_report,
    pair_from_audit_item,
    validate_report_shape,
)

SYSTEM_PROMPT = """You are a product-listing pre-verification auditor for Mercado Livre.
You compare one CATÁLOGO ad vs one TRADICIONAL ad for the SAME seller SKU.

Rules:
1) Metadata truth is provided in the user JSON. Do NOT invent TITULO, EAN, COR, or VOLTAGEM.
2) For metadata fields, confirm the provided mismatch flags; you may only add nuance in note_pt, not override hard mismatches.
3) For images: decide if both galleries show the SAME physical retail product (same model/SKU family). Flag differences in brand logo, model family, packaging SKU markings, colorway, or voltage markings visible on packaging.
4) Different category or form-factor (e.g. blender vs toaster) is always visual verdict=mismatch. differences_pt must then be non-empty.
5) If images are insufficient, blurry, placeholder, or lifestyle-only, return visual.verdict="uncertain" and lower confidence.
6) Never approve silently: if any hard metadata mismatch exists, overall_recommendation must be "reject" or "needs_human_review".
7) Output MUST match the JSON schema exactly. No markdown.
"""

FIELD_CMP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["catalogo", "tradicional", "status", "note_pt"],
    "properties": {
        "catalogo": {"type": "string"},
        "tradicional": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["OK", "DIVERGENTE", "AMBOS_VAZIOS", "AUSENTE_CAT", "AUSENTE_TRAD"],
        },
        "note_pt": {"type": "string"},
    },
}

REPORT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sku",
        "metadata",
        "visual",
        "scores",
        "overall_recommendation",
        "summary_pt",
        "mismatch_flags",
    ],
    "properties": {
        "sku": {"type": "string"},
        "metadata": {
            "type": "object",
            "additionalProperties": False,
            "required": ["titulo", "ean", "cor", "voltagem"],
            "properties": {
                "titulo": FIELD_CMP_SCHEMA,
                "ean": FIELD_CMP_SCHEMA,
                "cor": FIELD_CMP_SCHEMA,
                "voltagem": FIELD_CMP_SCHEMA,
            },
        },
        "visual": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "same_physical_product",
                "verdict",
                "confidence",
                "differences_pt",
                "evidence_pt",
            ],
            "properties": {
                "same_physical_product": {"type": "boolean"},
                "verdict": {"type": "string", "enum": ["match", "mismatch", "uncertain"]},
                "confidence": {"type": "number"},
                "differences_pt": {"type": "array", "items": {"type": "string"}},
                "evidence_pt": {"type": "array", "items": {"type": "string"}},
            },
        },
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "metadata_match_score",
                "visual_similarity_score",
                "overall_confidence",
            ],
            "properties": {
                "metadata_match_score": {"type": "number"},
                "visual_similarity_score": {"type": "number"},
                "overall_confidence": {"type": "number"},
            },
        },
        "overall_recommendation": {
            "type": "string",
            "enum": ["approve_candidate", "reject", "needs_human_review"],
        },
        "summary_pt": {"type": "string"},
        "mismatch_flags": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "titulo_mismatch",
                "ean_mismatch",
                "cor_mismatch",
                "voltagem_mismatch",
                "visual_mismatch",
            ],
            "properties": {
                "titulo_mismatch": {"type": "boolean"},
                "ean_mismatch": {"type": "boolean"},
                "cor_mismatch": {"type": "boolean"},
                "voltagem_mismatch": {"type": "boolean"},
                "visual_mismatch": {"type": "boolean"},
            },
        },
    },
}


def _trim_images(urls: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        cleaned = str(url or "").strip()
        if not cleaned or cleaned in seen:
            continue
        if cleaned.startswith("http://"):
            cleaned = "https://" + cleaned[len("http://") :]
        if not cleaned.startswith("https://"):
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def build_messages(pair: dict, metadata_preview: dict) -> list[dict]:
    cat_imgs = _trim_images(pair["catalogo"].get("image_urls") or [], OPENAI_MAX_IMAGES_PER_SIDE)
    trad_imgs = _trim_images(pair["tradicional"].get("image_urls") or [], OPENAI_MAX_IMAGES_PER_SIDE)

    payload = {
        "sku": pair.get("sku"),
        "catalogo": {
            "mlb": pair["catalogo"].get("mlb"),
            "titulo": pair["catalogo"].get("titulo"),
            "ean": pair["catalogo"].get("ean"),
            "cor": pair["catalogo"].get("cor"),
            "voltagem": pair["catalogo"].get("voltagem"),
        },
        "tradicional": {
            "mlb": pair["tradicional"].get("mlb"),
            "titulo": pair["tradicional"].get("titulo"),
            "ean": pair["tradicional"].get("ean"),
            "cor": pair["tradicional"].get("cor"),
            "voltagem": pair["tradicional"].get("voltagem"),
        },
        "metadata_flags": metadata_preview.get("mismatch_flags"),
        "metadata_status": {
            key: metadata_preview[key]["status"]
            for key in ("titulo", "ean", "cor", "voltagem")
        },
        "instructions": (
            "Compare the labeled CATÁLOGO vs TRADICIONAL images. "
            "If form-factor or product family differs, visual.verdict must be mismatch."
        ),
    }

    content: list[dict] = [
        {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
    ]
    for idx, url in enumerate(cat_imgs, start=1):
        content.append({"type": "text", "text": f"CATALOGO_IMAGE_{idx}"})
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
    for idx, url in enumerate(trad_imgs, start=1):
        content.append({"type": "text", "text": f"TRADICIONAL_IMAGE_{idx}"})
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def build_chat_payload(pair: dict, metadata_preview: dict) -> dict:
    return {
        "model": OPENAI_VISION_MODEL,
        "temperature": 0,
        "messages": build_messages(pair, metadata_preview),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ad_prevalidation_report",
                "strict": True,
                "schema": REPORT_JSON_SCHEMA,
            },
        },
    }


def parse_model_json(raw_content: str) -> dict:
    text = (raw_content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PrevalidationError("invalid_json", f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise PrevalidationError("invalid_json", "Resposta da IA não é um objeto JSON.")
    return data


def _post_chat_completions(payload: dict, api_key: str) -> dict:
    url = f"{OPENAI_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise PrevalidationError("timeout", "Tempo esgotado ao consultar a IA.") from exc
    except requests.RequestException as exc:
        raise PrevalidationError("upstream_4xx", f"Falha de rede na IA: {exc}") from exc

    if resp.status_code >= 500:
        raise PrevalidationError("upstream_4xx", f"IA indisponível (HTTP {resp.status_code}).")
    if resp.status_code >= 400:
        raise PrevalidationError("upstream_4xx", f"IA recusou a requisição (HTTP {resp.status_code}).")

    try:
        body = resp.json()
    except ValueError as exc:
        raise PrevalidationError("invalid_json", "Resposta da IA não é JSON.") from exc
    return body


def extract_message_content(body: dict) -> str:
    try:
        return str(body["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise PrevalidationError("invalid_json", "Estrutura inesperada na resposta da IA.") from exc


Completer = Callable[[dict], dict]


def run_prevalidation(
    item: dict,
    *,
    api_key: str | None = None,
    completer: Completer | None = None,
) -> dict:
    pair = pair_from_audit_item(item)
    if not pair.get("sku"):
        raise PrevalidationError("invalid_payload", "SKU obrigatório.")

    meta_preview = compute_metadata_flags(pair)
    cat_imgs = _trim_images(pair["catalogo"].get("image_urls") or [], OPENAI_MAX_IMAGES_PER_SIDE)
    trad_imgs = _trim_images(pair["tradicional"].get("image_urls") or [], OPENAI_MAX_IMAGES_PER_SIDE)
    has_images = bool(cat_imgs) and bool(trad_imgs)

    if not has_images:
        report = merge_report(
            pair,
            None,
            visual_fallback=empty_visual(
                "uncertain",
                0.2,
                ["Uma ou ambas as galerias estão sem imagens suficientes para análise visual."],
            ),
        )
        ok, reason = validate_report_shape(report)
        if not ok:
            raise PrevalidationError("invalid_json", reason)
        return report

    key = (api_key if api_key is not None else OPENAI_API_KEY).strip()
    if completer is None and not key:
        raise PrevalidationError("missing_key", "OPENAI_API_KEY não configurada no servidor.")

    payload = build_chat_payload(pair, meta_preview)
    body = completer(payload) if completer else _post_chat_completions(payload, key)
    raw = extract_message_content(body)
    vision = parse_model_json(raw)
    report = merge_report(pair, vision)
    ok, reason = validate_report_shape(report)
    if not ok:
        raise PrevalidationError("invalid_json", reason)
    return report
