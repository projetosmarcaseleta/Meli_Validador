# n8n — Consulta conta por OI (rede DB1)

Workflow n8n (support-app): **U4oqQCvEYnDAYgAm**  
Arquivo no repo: `deploy/n8n-workflow-consultar-conta-oi.json`

## Webhook (produção)

- **Path:** `consultar-conta-anymarket`
- **URL exemplo:** `https://api.marcaseleta.shop/webhook/consultar-conta-anymarket`

## Corpo POST (JSON)

**Busca por nome:**

```json
{ "action": "search", "q": "Kabum" }
```

**Seleção por OI (token ML):**

```json
{ "action": "select", "oi": "259063586.", "client_name": "KABUM" }
```

Também aceita só dígitos em `q` (ex.: `"259063586"`) — o workflow normaliza para `259063586.` e segue rota `select`.

## Credencial no n8n

Crie **Header Auth** (`Support App Bearer`):

- **Name:** `Authorization`
- **Value:** `Bearer <ANYMARKET_SUPPORT_TOKEN>`

Associe nos nós **HTTP Marketplaces por OI** e **HTTP Busca por Nome**.

## VPS / validador

No `.env` da aplicação:

```env
ANYMARKET_CLIENT_WEBHOOK_URL=https://api.marcaseleta.shop/webhook/consultar-conta-anymarket
```

Reinicie `meli-validador`. O front busca por **OI ou nome**; a VPS chama o n8n (rede DB1), não a support-app diretamente.

## Resposta vazia (HTTP 200)

Se o webhook responder **200 sem JSON**, o workflow não chegou no nó **Responder Webhook** (HTTP support-app falhou, credencial Bearer ausente ou workflow desatualizado). Reimporte `deploy/n8n-workflow-consultar-conta-oi.json`, vincule a credencial **Support App Bearer** e **ative** o workflow.

## SKU + OI

Workflow réplica Postgres: **zAxE6ZpLgyLyFqu7** → webhook `consultar-skus-anymarket`  
Arquivo: `deploy/n8n-workflow-anymarket-skus.json`

POST (exemplo):

```json
{
  "skus": ["SKU1", "SKU2"],
  "oi": "259063586.",
  "client_id": "support:259063586"
}
```

O nó **Preparar SKUs1** normaliza o OI (ou extrai de `support:123456789`) e o Postgres filtra `s.oi = '<digits>.'`. Sem OI, o workflow responde erro JSON (não consulta todas as contas).
