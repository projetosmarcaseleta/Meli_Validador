"""
prevalidation.py – Gate determinístico TITULO / EAN / COR / VOLTAGEM
e política de recomendação (fail-closed) da pré-validação IA.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from anymarket_api import match_values, normalize_for_match

PROMPT_VERSION = "v1.0"

FIELD_STATUS = ("OK", "DIVERGENTE", "AMBOS_VAZIOS", "AUSENTE_CAT", "AUSENTE_TRAD")
VISUAL_VERDICTS = ("match", "mismatch", "uncertain")
RECOMMENDATIONS = ("approve_candidate", "reject", "needs_human_review")

METADATA_KEYS = ("titulo", "ean", "cor", "voltagem")


class PrevalidationError(Exception):
    def __init__(self, detail: str, message: str | None = None):
        self.detail = detail
        super().__init__(message or detail)


def normalize_voltage(value: str) -> str:
    text = normalize_for_match(value)
    text = text.replace("volts", "v").replace("volt", "v")
    text = re.sub(r"[\s\-_/]", "", text)
    if "bivolt" in text or text in {"127220", "110220", "220110", "127v220v"}:
        return "bivolt"
    match = re.search(r"(\d{2,3})v?", text)
    if match:
        return f"{match.group(1)}v"
    return text


def normalize_ean(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_color(value: str) -> str:
    return normalize_for_match(value)


def normalize_title(value: str) -> str:
    return normalize_for_match(value)


def _map_pair_status(status: str) -> str:
    if status == "AUSENTE_ML":
        return "AUSENTE_CAT"
    if status == "AUSENTE_ANY":
        return "AUSENTE_TRAD"
    return status


def compare_field(catalogo: str, tradicional: str, normalizer: Callable[[str], str] | None = None) -> str:
    left = normalizer(catalogo) if normalizer else str(catalogo or "")
    right = normalizer(tradicional) if normalizer else str(tradicional or "")
    return _map_pair_status(match_values(left, right))


def _image_urls(side: dict) -> list[str]:
    urls = side.get("image_urls")
    if isinstance(urls, list) and urls:
        return [str(u).strip() for u in urls if str(u).strip()]
    images_list = side.get("images_list")
    if isinstance(images_list, list) and images_list:
        return [str(u).strip() for u in images_list if str(u).strip()]
    main = str(side.get("image_main") or "").strip()
    return [main] if main else []


def pair_from_audit_item(item: dict) -> dict:
    cat = item.get("catalogo") or item.get("ml") or {}
    trad = item.get("tradicional") or item.get("any") or {}
    return {
        "sku": str(item.get("sku") or ""),
        "catalogo": {
            "mlb": str(item.get("mlb_cat") or cat.get("mlb") or ""),
            "titulo": str(cat.get("titulo") or cat.get("title") or ""),
            "ean": str(cat.get("ean") or ""),
            "cor": str(cat.get("cor") or cat.get("color") or ""),
            "voltagem": str(cat.get("voltagem") or cat.get("voltage") or ""),
            "image_urls": _image_urls(cat),
        },
        "tradicional": {
            "mlb": str(item.get("mlb_trad") or trad.get("mlb") or ""),
            "titulo": str(trad.get("titulo") or trad.get("title") or ""),
            "ean": str(trad.get("ean") or ""),
            "cor": str(trad.get("cor") or trad.get("color") or ""),
            "voltagem": str(trad.get("voltagem") or trad.get("voltage") or ""),
            "image_urls": _image_urls(trad),
        },
    }


def compute_metadata_flags(pair: dict) -> dict:
    cat = pair["catalogo"]
    trad = pair["tradicional"]
    titulo_status = compare_field(cat["titulo"], trad["titulo"], normalize_title)
    ean_status = compare_field(cat["ean"], trad["ean"], normalize_ean)
    cor_status = compare_field(cat["cor"], trad["cor"], normalize_color)
    voltagem_status = compare_field(cat["voltagem"], trad["voltagem"], normalize_voltage)

    def is_mismatch(status: str) -> bool:
        return status == "DIVERGENTE"

    return {
        "titulo": {
            "catalogo": cat["titulo"],
            "tradicional": trad["titulo"],
            "status": titulo_status,
        },
        "ean": {
            "catalogo": cat["ean"],
            "tradicional": trad["ean"],
            "status": ean_status,
        },
        "cor": {
            "catalogo": cat["cor"],
            "tradicional": trad["cor"],
            "status": cor_status,
        },
        "voltagem": {
            "catalogo": cat["voltagem"],
            "tradicional": trad["voltagem"],
            "status": voltagem_status,
        },
        "mismatch_flags": {
            "titulo_mismatch": is_mismatch(titulo_status),
            "ean_mismatch": is_mismatch(ean_status),
            "cor_mismatch": is_mismatch(cor_status),
            "voltagem_mismatch": is_mismatch(voltagem_status),
        },
    }


def metadata_match_score(flags: dict) -> float:
    mismatches = sum(1 for key in ("titulo_mismatch", "ean_mismatch", "cor_mismatch", "voltagem_mismatch") if flags.get(key))
    return round(1.0 - (mismatches / 4.0), 4)


def apply_recommendation_policy(
    metadata_flags: dict,
    visual_verdict: str,
    visual_confidence: float,
) -> str:
    hard_mismatch = any(
        metadata_flags.get(key)
        for key in ("titulo_mismatch", "ean_mismatch", "cor_mismatch", "voltagem_mismatch")
    )
    visual_mismatch = visual_verdict == "mismatch"

    if hard_mismatch and visual_mismatch:
        return "reject"
    if hard_mismatch:
        return "needs_human_review"
    if visual_mismatch:
        return "reject"
    if visual_verdict == "uncertain" or visual_confidence < 0.55:
        return "needs_human_review"
    return "approve_candidate"


def _field_cmp(meta_block: dict, model_note: str = "") -> dict:
    return {
        "catalogo": str(meta_block.get("catalogo") or ""),
        "tradicional": str(meta_block.get("tradicional") or ""),
        "status": meta_block.get("status") or "AMBOS_VAZIOS",
        "note_pt": str(model_note or ""),
    }


def empty_visual(verdict: str = "uncertain", confidence: float = 0.0, differences: list[str] | None = None) -> dict:
    return {
        "same_physical_product": verdict == "match",
        "verdict": verdict,
        "confidence": confidence,
        "differences_pt": differences or [],
        "evidence_pt": [],
    }


def merge_report(pair: dict, vision: dict | None, *, visual_fallback: dict | None = None) -> dict:
    meta = compute_metadata_flags(pair)
    flags = dict(meta["mismatch_flags"])
    vision = vision or {}
    visual = vision.get("visual") or visual_fallback or empty_visual()

    verdict = visual.get("verdict") if visual.get("verdict") in VISUAL_VERDICTS else "uncertain"
    try:
        v_conf = float(visual.get("confidence") or 0)
    except (TypeError, ValueError):
        v_conf = 0.0
    v_conf = max(0.0, min(1.0, v_conf))

    flags["visual_mismatch"] = verdict == "mismatch"
    meta_score = metadata_match_score(flags)
    visual_score = v_conf if verdict == "match" else (0.0 if verdict == "mismatch" else min(v_conf, 0.49))
    recommendation = apply_recommendation_policy(flags, verdict, v_conf)

    model_meta = vision.get("metadata") or {}
    notes = {}
    for key in METADATA_KEYS:
        block = model_meta.get(key) if isinstance(model_meta.get(key), dict) else {}
        notes[key] = str(block.get("note_pt") or "")

    summary = str(vision.get("summary_pt") or "").strip()
    if not summary:
        summary = _default_summary(flags, verdict)

    differences = visual.get("differences_pt") or []
    if not isinstance(differences, list):
        differences = [str(differences)]
    evidence = visual.get("evidence_pt") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)]

    return {
        "sku": str(pair.get("sku") or vision.get("sku") or ""),
        "metadata": {
            key: _field_cmp(meta[key], notes.get(key, ""))
            for key in METADATA_KEYS
        },
        "visual": {
            "same_physical_product": verdict == "match",
            "verdict": verdict,
            "confidence": v_conf,
            "differences_pt": [str(x) for x in differences],
            "evidence_pt": [str(x) for x in evidence],
        },
        "scores": {
            "metadata_match_score": meta_score,
            "visual_similarity_score": round(float(visual_score), 4),
            "overall_confidence": round((meta_score * 0.55) + (float(visual_score) * 0.45), 4),
        },
        "overall_recommendation": recommendation,
        "summary_pt": summary,
        "mismatch_flags": flags,
    }


def _default_summary(flags: dict, verdict: str) -> str:
    parts = []
    labels = {
        "titulo_mismatch": "Título divergente",
        "ean_mismatch": "EAN divergente",
        "cor_mismatch": "Cor divergente",
        "voltagem_mismatch": "Voltagem divergente",
        "visual_mismatch": "Imagens de produtos diferentes",
    }
    for key, label in labels.items():
        if flags.get(key):
            parts.append(label)
    if not parts and verdict == "uncertain":
        return "Metadados conferem; análise visual inconclusiva — revisão humana necessária."
    if not parts:
        return "Metadados e imagens consistentes entre Catálogo e Tradicional."
    return "; ".join(parts) + "."


REQUIRED_REPORT_KEYS = (
    "sku",
    "metadata",
    "visual",
    "scores",
    "overall_recommendation",
    "summary_pt",
    "mismatch_flags",
)


def validate_report_shape(report: Any) -> tuple[bool, str]:
    if not isinstance(report, dict):
        return False, "report_not_object"
    for key in REQUIRED_REPORT_KEYS:
        if key not in report:
            return False, f"missing_{key}"
    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        return False, "metadata_not_object"
    for key in METADATA_KEYS:
        block = metadata.get(key)
        if not isinstance(block, dict):
            return False, f"metadata_{key}_invalid"
        for field in ("catalogo", "tradicional", "status", "note_pt"):
            if field not in block:
                return False, f"metadata_{key}_missing_{field}"
        if block["status"] not in FIELD_STATUS:
            return False, f"metadata_{key}_bad_status"
    visual = report.get("visual")
    if not isinstance(visual, dict) or visual.get("verdict") not in VISUAL_VERDICTS:
        return False, "visual_invalid"
    flags = report.get("mismatch_flags")
    if not isinstance(flags, dict):
        return False, "flags_invalid"
    for key in ("titulo_mismatch", "ean_mismatch", "cor_mismatch", "voltagem_mismatch", "visual_mismatch"):
        if not isinstance(flags.get(key), bool):
            return False, f"flag_{key}_not_bool"
    if report.get("overall_recommendation") not in RECOMMENDATIONS:
        return False, "bad_recommendation"
    return True, "ok"
