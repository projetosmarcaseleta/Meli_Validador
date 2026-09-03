# Seleta Auditor ML

Auditoria de anúncios **Catálogo × Tradicional** no Mercado Livre — compara fotos, preços, status e atributos por SKU, com exportação para Excel.

## Primeira vez — como iniciar

Para abrir o programa pela **primeira vez**, use o atalho:

**Seleta Auditor ML**

Esse é o ponto de entrada do sistema. Ao executá-lo, o servidor local sobe e o navegador abre a interface do auditor.

> Se o atalho **Seleta Auditor ML** ainda não existir na sua máquina, peça à equipe de TI ou crie um atalho que inicie o servidor e abra http://127.0.0.1:3010/ no navegador.

## Uso rápido

1. Abra **Seleta Auditor ML**.
2. Cole o **token do Mercado Livre** e clique em **Validar Token**.
3. Informe os **SKUs** (ou importe uma planilha).
4. Clique em **Auditar Catálogo vs Tradicional**.
5. Revise os resultados e use **Exportar Todos** para baixar a planilha.

## Configuração (opcional)

Copie .env.example para .env na pasta Meli_Exporter e preencha as variáveis necessárias (token ML, credenciais AnyMarket, etc.).

## Estrutura

| Pasta / arquivo | Descrição |
|---|---|
| ml_exporter/app.py | Servidor Flask |
| ml_exporter/templates/index.html | Interface web |
| ml_exporter/exporter.py | Busca ML + cruzamento Catálogo/Tradicional |
| scripts/ | Scripts de teste e diagnóstico |

## Produção

Deploy documentado em deploy/ (VPS, nginx, systemd). URL pública padrão: https://app.marcaseleta.shop/export
