"""
app.py – Servidor Web Flask do Meli Triagem (Filtro e Exclusão Rápida)
"""

import os
import uuid
import requests as req
from flask import Flask, render_template, request, jsonify, send_file

from config import PORT, GOOGLE_SHEET_WEBHOOK_URL
from api import validate_token
from triage_engine import run_batch_triage
from exporter import generate_triage_excel

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "meli-triagem-secret-key")


@app.route("/")
def index():
    return render_template(
        "index.html",
        default_webhook_url=GOOGLE_SHEET_WEBHOOK_URL or "",
    )


@app.route("/api/validate_token", methods=["POST"])
def api_validate_token():
    data = request.json or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"valid": False, "error": "Token vazio."}), 400

    user = validate_token(token)
    if user and user.get("id"):
        return jsonify({
            "valid": True,
            "id": user.get("id"),
            "nickname": user.get("nickname"),
        })
    return jsonify({"valid": False, "error": "Token inválido ou expirado."}), 401


@app.route("/api/triage", methods=["POST"])
def api_triage():
    data = request.json or {}
    token = (data.get("token") or "").strip()
    inputs = data.get("inputs") or []

    if not token:
        return jsonify({"success": False, "error": "Token do Mercado Livre é obrigatório."}), 400
    if not inputs:
        return jsonify({"success": False, "error": "Informe uma lista de MLBs ou SKUs para triagem."}), 400

    try:
        results = run_batch_triage(inputs, token)
        return jsonify({
            "success": True,
            "summary": results.get("summary", {}),
            "items": results.get("items", []),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": f"Erro interno durante a triagem: {str(exc)}"}), 500


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.json or {}
    items = data.get("items") or []
    selected_ids = set(data.get("selected_ids") or [])
    filter_cat = (data.get("filter_category") or "all").strip().lower()

    if not items:
        return jsonify({"success": False, "error": "Nenhum item para exportar."}), 400

    try:
        buf = generate_triage_excel(
            items=items,
            selected_ids=selected_ids if selected_ids else None,
            filter_category=filter_cat,
        )
        prefix = "Descartados" if filter_cat == "hard" else ("Aptos" if filter_cat == "clean" else "Triagem_Meli")
        filename = f"{prefix}_{uuid.uuid4().hex[:6]}.xlsx"

        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        return jsonify({"success": False, "error": f"Erro ao gerar planilha: {str(exc)}"}), 500


@app.route("/api/sync_google_sheet", methods=["POST"])
def api_sync_google_sheet():
    data = request.json or {}
    webhook_url = (data.get("webhook_url") or GOOGLE_SHEET_WEBHOOK_URL or "").strip()
    items = data.get("items") or []
    status_to_mark = data.get("status") or "Incorreto"

    if not webhook_url:
        return jsonify({"success": False, "error": "Webhook do Google Apps Script não configurado."}), 400
    if not items:
        return jsonify({"success": False, "error": "Nenhum anúncio para sincronizar."}), 400

    payload = {
        "items": [
            {
                "mlb": str(it.get("mlb_cat") or it.get("mlb_trad") or it.get("mlb") or "").strip(),
                "sku": str(it.get("sku") or "").strip(),
                "status": status_to_mark,
                "motivo": str(it.get("reasons_summary") or "").strip(),
            }
            for it in items
            if (it.get("mlb_cat") or it.get("mlb_trad") or it.get("mlb"))
        ]
    }

    try:
        resp = req.post(webhook_url, json=payload, timeout=30)
        if resp.status_code == 200:
            return jsonify({"success": True, "result": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}})
        return jsonify({"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}), 502
    except Exception as exc:
        return jsonify({"success": False, "error": f"Erro de conexão com o webhook: {str(exc)}"}), 500


if __name__ == "__main__":
    print(f"🚀 Iniciando Meli Triagem na porta {PORT}...")
    app.run(host="0.0.0.0", port=PORT, debug=True)
