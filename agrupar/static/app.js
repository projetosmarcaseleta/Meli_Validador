const TOKEN_KEY = "agrupar.token.sessao"
const VALIDACAO_KEY = "agrupar.validacao.sessao"

const form = document.getElementById("form-executar")
const campoToken = document.getElementById("token")
const campoMlbs = document.getElementById("mlbs")
const campoGenero = document.getElementById("genero")
const campoFamilyName = document.getElementById("family-name")
const campoRevalidacao = document.getElementById("revalidacao")
const chkIrmaos = document.getElementById("expandir-irmaos")
const chkVendas = document.getElementById("tentar-vendas")
const chkLembrar = document.getElementById("lembrar-token")
const btnSimular = document.getElementById("btn-simular")
const btnAplicar = document.getElementById("btn-aplicar")
const btnValidar = document.getElementById("btn-validar")
const btnVerToken = document.getElementById("btn-ver-token")
const btnLimpar = document.getElementById("btn-limpar")
const btnCopiar = document.getElementById("btn-copiar-relatorio")
const btnCopiarValidador = document.getElementById("btn-copiar-validador")
const btnPdfValidador = document.getElementById("btn-pdf-validador")
const btnMarkdownValidador = document.getElementById("btn-markdown-validador")
const tabLogs = document.getElementById("tab-logs")
const tabRelatorio = document.getElementById("tab-relatorio")
const tabValidador = document.getElementById("tab-validador")
const painelLogs = document.getElementById("painel-logs")
const painelRelatorio = document.getElementById("painel-relatorio")
const painelValidador = document.getElementById("painel-validador")
const validadorVazio = document.getElementById("validador-vazio")
const validadorConteudo = document.getElementById("validador-conteudo")
const validadorStatus = document.getElementById("validador-status")
const validadorResumo = document.getElementById("validador-resumo")
const validadorStats = document.getElementById("validador-stats")
const validadorAvisos = document.getElementById("validador-avisos")
const validadorOportunidades = document.getElementById("validador-oportunidades")
const validadorJaAgrupados = document.getElementById("validador-ja-agrupados")
const tabelaValidadorFamilias = document.getElementById("tabela-validador-familias")
const listaIsolados = document.getElementById("lista-isolados")
const tabelaValidadorMlbs = document.getElementById("tabela-validador-mlbs")
const validadorTexto = document.getElementById("validador-texto")
const consoleLogs = document.getElementById("console-logs")
const statusExecucao = document.getElementById("status-execucao")
const contadorMlbs = document.getElementById("contador-mlbs")
const relatorioVazio = document.getElementById("relatorio-vazio")
const relatorioConteudo = document.getElementById("relatorio-conteudo")
const relatorioModo = document.getElementById("relatorio-modo")
const relatorioStatus = document.getElementById("relatorio-status")
const relatorioResumo = document.getElementById("relatorio-resumo")
const relatorioStats = document.getElementById("relatorio-stats")
const relatorioAvisos = document.getElementById("relatorio-avisos")
const relatorioDownloads = document.getElementById("relatorio-downloads")
const relatorioTexto = document.getElementById("relatorio-texto")
const tabelaFamilias = document.getElementById("tabela-familias")
const listaMigracoes = document.getElementById("lista-migracoes")
const tabelaPutsErro = document.getElementById("tabela-puts-erro")
const tabelaMlbs = document.getElementById("tabela-mlbs")

let ultimoTextoRelatorio = ""
let ultimoTextoValidador = ""
let ultimoResultadoValidacao = null

const CLASSE_TAB_ATIVA =
  "tab-btn rounded-md px-3 py-1.5 text-sm font-medium bg-ink text-acid border border-line"
const CLASSE_TAB_INATIVA =
  "tab-btn rounded-md px-3 py-1.5 text-sm font-medium text-zinc-400 hover:text-white"

function contarEntrada(texto) {
  const vistosMlb = new Set()
  const vistosSku = new Set()
  for (const parte of texto.split(/[\s,;]+/)) {
    const token = parte.trim()
    if (!token || token.startsWith("#")) continue
    const mlb = token.toUpperCase()
    if (/^MLB\d+$/.test(mlb)) {
      vistosMlb.add(mlb)
      continue
    }
    if (/\d/.test(token) && /^[A-Za-z0-9._-]+$/i.test(token)) {
      vistosSku.add(token)
    }
  }
  return { mlbs: vistosMlb.size, skus: vistosSku.size, total: vistosMlb.size + vistosSku.size }
}

function atualizarContador() {
  const c = contarEntrada(campoMlbs.value)
  if (c.skus && c.mlbs) contadorMlbs.textContent = `${c.mlbs} MLB · ${c.skus} SKU`
  else if (c.skus) contadorMlbs.textContent = `${c.skus} SKU`
  else contadorMlbs.textContent = String(c.mlbs)
}

function horaLog(ts) {
  if (!ts) return "--:--:--"
  const data = new Date(ts)
  if (Number.isNaN(data.getTime())) return "--:--:--"
  return data.toLocaleTimeString("pt-BR", { hour12: false })
}

function rotuloNivel(level) {
  if (level === "error") return "ERRO"
  if (level === "warn") return "AVISO"
  if (level === "ok") return "OK"
  return "INFO"
}

function corNivel(level) {
  if (level === "error") return "text-red-400"
  if (level === "warn") return "text-acid"
  if (level === "ok") return "text-emerald-400"
  return "text-zinc-500"
}

function adicionarLog(evento) {
  const linha = document.createElement("div")
  const level = evento.level || "info"
  linha.className = "log-line"
  linha.dataset.level = level
  linha.innerHTML = `
    <span class="text-zinc-600">${horaLog(evento.ts)}</span>
    <span class="${corNivel(level)}">${rotuloNivel(level)}</span>
    <span class="text-zinc-200 break-all">${escapeHtml(evento.message || "")}</span>
  `
  consoleLogs.appendChild(linha)
  painelLogs.scrollTop = painelLogs.scrollHeight
}

function escapeHtml(texto) {
  return String(texto ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

function ativarAba(nome) {
  const abas = {
    logs: { tab: tabLogs, painel: painelLogs },
    relatorio: { tab: tabRelatorio, painel: painelRelatorio },
    validador: { tab: tabValidador, painel: painelValidador },
  }
  for (const [id, { tab, painel }] of Object.entries(abas)) {
    const ativa = id === nome
    tab.setAttribute("aria-selected", ativa ? "true" : "false")
    tab.className = ativa ? CLASSE_TAB_ATIVA : CLASSE_TAB_INATIVA
    painel.classList.toggle("hidden", !ativa)
  }
}

function limparLogs() {
  consoleLogs.innerHTML = ""
  statusExecucao.textContent = "parado"
}

function montarPedido(aplicar) {
  return {
    token: campoToken.value,
    mlbs: campoMlbs.value,
    aplicar,
    genero: campoGenero.value,
    family_name: campoFamilyName.value,
    expandir_irmaos: chkIrmaos.checked,
    tentar_family_name_com_vendas: chkVendas.checked,
    revalidacao_segundos: Number(campoRevalidacao.value || 45),
  }
}

function setRodando(rodando) {
  btnSimular.disabled = rodando
  btnAplicar.disabled = rodando
  btnValidar.disabled = rodando
  statusExecucao.textContent = rodando ? "executando…" : "parado"
}

function cardStat(rotulo, valor) {
  return `
    <div class="rounded-md border border-line bg-panel px-3 py-2">
      <p class="text-[11px] uppercase tracking-wide text-zinc-500">${escapeHtml(rotulo)}</p>
      <p class="font-mono text-sm text-white mt-1">${escapeHtml(String(valor ?? "—"))}</p>
    </div>
  `
}

function htmlRaiox(item) {
  const fmt = (mapa) =>
    Object.entries(mapa || {})
      .map(([chave, valor]) => `${chave}=${valor || "—"}`)
      .join(" · ")
  const parent = fmt(item.parent_pk)
  const child = fmt(item.child_pk)
  if (!parent && !child) return ""
  return `
    <div class="mt-1 text-[11px] font-mono text-zinc-400 break-all">
      <div><span class="text-acid">PARENT_PK</span> ${escapeHtml(parent || "—")}</div>
      <div><span class="text-acid">CHILD_PK</span> ${escapeHtml(child || "—")}</div>
    </div>
  `
}

function setCelulasVazias(tabela, colunas, mensagem) {
  tabela.innerHTML = `
    <tr class="border-t border-line">
      <td class="py-2 text-zinc-500" colspan="${colunas}">${escapeHtml(mensagem)}</td>
    </tr>
  `
}

function setaSeMudou(antes, depois, mudou) {
  const a = antes || "—"
  const d = depois || a
  if (!mudou && a === d) return escapeHtml(String(a))
  return `${escapeHtml(String(a))} → ${escapeHtml(String(d))}`
}

function mostrarResultado(resultado) {
  if (!resultado) return
  relatorioVazio.classList.add("hidden")
  relatorioConteudo.classList.remove("hidden")
  const modo = resultado.dry_run ? "simulação · PUTs não enviados" : "APPLY"
  const status = resultado.status_agrupamento || (resultado.ok ? "OK" : "FALHA")
  relatorioModo.textContent = modo
  relatorioStatus.textContent = status
  relatorioResumo.textContent = resultado.resumo || resultado.error || ""

  relatorioStats.innerHTML = [
    cardStat("MLBs", resultado.total_get_ok ?? resultado.total_origem ?? 0),
    cardStat(
      "Famílias",
      `${resultado.familias_antes ?? "—"} → ${resultado.familias_depois ?? "—"}`
    ),
    cardStat("Mudaram family_id", resultado.mudaram_family_id ?? 0),
    cardStat(
      "PUTs",
      `${resultado.puts_ok || 0} ok · ${resultado.puts_erro || 0} erro · ${resultado.puts_planejado || 0} plano`
    ),
  ].join("")

  const avisos = resultado.avisos || []
  if (avisos.length) {
    relatorioAvisos.classList.remove("hidden")
    relatorioAvisos.textContent = avisos.join(" ")
  } else {
    relatorioAvisos.classList.add("hidden")
    relatorioAvisos.textContent = ""
  }

  relatorioDownloads.innerHTML = ""
  for (const arquivo of resultado.arquivos || []) {
    const link = document.createElement("a")
    link.href = arquivo.url
    link.download = arquivo.nome
    link.className =
      "rounded-md border border-line px-3 py-1.5 text-xs text-acid hover:bg-panel"
    link.textContent = `Baixar ${arquivo.rotulo}`
    relatorioDownloads.appendChild(link)
  }

  tabelaFamilias.innerHTML = ""
  const familias = resultado.listagem_family_name || []
  if (!familias.length) {
    setCelulasVazias(tabelaFamilias, 6, "Nenhuma família neste lote.")
  }
  for (const bloco of familias) {
    const tr = document.createElement("tr")
    tr.className = "border-t border-line align-top"
    const puts = `${bloco.quantidade_puts_ok || 0} ok / ${bloco.quantidade_puts_erro || 0} erro`
    tr.innerHTML = `
      <td class="py-2 pr-3 font-mono text-acid">${bloco.n || 0}</td>
      <td class="py-2 pr-3 text-zinc-200">${escapeHtml(bloco.family_name || "")}</td>
      <td class="py-2 pr-3 font-mono">${bloco.vendas || 0}</td>
      <td class="py-2 pr-3 text-zinc-400">${escapeHtml((bloco.gender || []).join(", "))}</td>
      <td class="py-2 pr-3 font-mono">${escapeHtml(puts)}</td>
      <td class="py-2 text-zinc-400">${escapeHtml(bloco.da_para_juntar || "")}</td>
    `
    tabelaFamilias.appendChild(tr)
  }

  const fluxos = resultado.fluxos_family_id || []
  listaMigracoes.innerHTML = ""
  if (!fluxos.length) {
    listaMigracoes.innerHTML =
      '<li class="text-zinc-500">Nenhuma mudança de family_id nesta execução.</li>'
  }
  for (const fluxo of fluxos) {
    const li = document.createElement("li")
    li.textContent = `${fluxo.quantidade} item(ns): ${fluxo.family_id_antes} → ${fluxo.family_id_depois}`
    listaMigracoes.appendChild(li)
  }

  tabelaPutsErro.innerHTML = ""
  const erros = resultado.puts_erro_detalhe || []
  if (!erros.length) {
    setCelulasVazias(tabelaPutsErro, 4, "Nenhum PUT com erro.")
  }
  for (const put of erros) {
    const tr = document.createElement("tr")
    tr.className = "border-t border-line align-top"
    tr.innerHTML = `
      <td class="py-2 pr-3 font-mono">${escapeHtml(put.mlb || "")}</td>
      <td class="py-2 pr-3">${escapeHtml(put.request_type || "")}</td>
      <td class="py-2 pr-3 font-mono">${escapeHtml(put.status_code || "")}</td>
      <td class="py-2 text-red-300">${escapeHtml(put.mensagem_api || "")}${put.body ? `<div class="text-zinc-500 mt-1">${escapeHtml(put.body)}</div>` : ""}</td>
    `
    tabelaPutsErro.appendChild(tr)
  }

  tabelaMlbs.innerHTML = ""
  const mlbs = resultado.detalhe_mlbs || []
  if (!mlbs.length) {
    setCelulasVazias(tabelaMlbs, 5, "Sem detalhe de MLB (GET falhou ou lote vazio).")
  }
  for (const item of mlbs) {
    const tr = document.createElement("tr")
    tr.className = "border-t border-line align-top"
    const putsTxt = `${item.puts_ok || 0} ok / ${item.puts_erro || 0} erro / ${item.puts_planejado || 0} plano`
    tr.innerHTML = `
      <td class="py-2 pr-3 font-mono">${escapeHtml(item.mlb || "")}${htmlRaiox(item)}</td>
      <td class="py-2 pr-3">${setaSeMudou(item.gender_antes, item.gender_depois, item.gender_mudou)}</td>
      <td class="py-2 pr-3 font-mono text-[11px]">${setaSeMudou(item.family_id_antes, item.family_id_depois, item.family_id_mudou)}</td>
      <td class="py-2 pr-3">${setaSeMudou(item.family_name_antes, item.family_name_depois, item.family_name_mudou)}</td>
      <td class="py-2 font-mono">${escapeHtml(putsTxt)}</td>
    `
    tabelaMlbs.appendChild(tr)
  }

  ultimoTextoRelatorio = resultado.texto || ""
  relatorioTexto.textContent = ultimoTextoRelatorio || "(sem texto de relatório)"
  ativarAba("relatorio")
}

function rotuloVia(via) {
  const mapa = {
    api: "API · PUT PARENT_PK",
    api_parcial: "API parcial (closed fica de fora)",
    api_com_risco_409: "API arriscada · 409 se o hash já existe",
    seller_center: "Seller Center · API não funde o nome",
    recalculo: "Aguardar recálculo",
    ja_ok: "Já agrupados",
    nao: "Não agrupável pela API",
  }
  return mapa[via] || via || "—"
}

function classeCard(via) {
  if (via === "ja_ok") return "border-emerald-700/50 bg-emerald-950/20"
  if (via === "api" || via === "api_parcial" || via === "recalculo") return "border-acid/50 bg-yellow-950/20"
  if (via === "api_com_risco_409" || via === "seller_center") return "border-orange-700/40 bg-orange-950/15"
  return "border-red-800/40 bg-red-950/15"
}

function rotuloVeredicto(veredicto) {
  const mapa = {
    ja_agrupados: "Já agrupados",
    ja_agrupado: "Já agrupado",
    agrupavel_gender: "Agrupável alinhando GENDER",
    agrupavel_parent_pk: "Agrupável alinhando PARENT_PK",
    hash_igual_family_id_diferente: "Hash igual · family_id ainda diferente",
    possivel_se_alterar_family_name: "Possível se alterar family_name",
    possivel_se_alterar_parent_e_family_name: "Possível se alterar PARENT_PK e family_name",
    bloqueado_closed: "Bloqueado · anúncio closed",
    bloqueado_child_pk: "Bloqueado · CHILD_PK inconsistente",
    bloqueado_age_group: "Bloqueado · AGE_GROUP",
    nao_agrupavel: "Não agrupável",
    isolado: "Isolado no lote",
  }
  return mapa[veredicto] || veredicto || "—"
}

function mdCelula(valor) {
  return String(valor ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("|", "\\|")
    .replaceAll("\n", "<br>")
}

function mdTabela(cabeca, linhas) {
  const cab = `| ${cabeca.map(mdCelula).join(" | ")} |`
  const sep = `| ${cabeca.map(() => "---").join(" | ")} |`
  const corpo = linhas
    .map((linha) => `| ${linha.map(mdCelula).join(" | ")} |`)
    .join("\n")
  return `${cab}\n${sep}\n${corpo}`
}

function markdownCard(bloco) {
  const linhas = [
    `### ${bloco.titulo || bloco.id || "Grupo"}`,
    "",
    `- **Via:** ${rotuloVia(bloco.via)}`,
    `- **Veredicto:** ${rotuloVeredicto(bloco.veredicto)}`,
  ]
  if (bloco.motivo) linhas.push(`- **Motivo:** ${bloco.motivo}`)
  const params = (bloco.parametros_a_alterar || []).join(", ")
  if (params) linhas.push(`- **Parâmetros a alterar:** ${params}`)
  if (bloco.cenario_hipotetico) linhas.push(`- **Cenário:** ${bloco.cenario_hipotetico}`)
  for (const bloqueio of bloco.bloqueios || []) {
    linhas.push(`- **Bloqueio:** ${bloqueio}`)
  }
  for (const fam of bloco.familias || []) {
    linhas.push(
      `- Família: ${fam.n || 0} · ${fam.family_name || "—"} · id=${fam.family_id || "—"} · vendas=${fam.vendas || 0}`
    )
  }
  for (const item of bloco.divergencias || []) {
    const valores = Object.entries(item.valores || {})
      .map(([valor, mlbs]) => `${valor} (${(mlbs || []).length})`)
      .join(" · ")
    linhas.push(`- Divergência ${item.campo}: ${valores}`)
  }
  const mlbs = bloco.mlbs || []
  if (mlbs.length) linhas.push(`- **MLBs:** ${mlbs.join(", ")}`)
  linhas.push("")
  return linhas.join("\n")
}

function markdownValidacao(resultado) {
  const c = resultado.contagens || {}
  const status = `${c.oportunidades || 0} oportunidade(s) · ${c.ja_agrupados || 0} já agrupado(s)`
  const cenario = [
    resultado.genero_alvo ? `GENDER hipotético: ${resultado.genero_alvo}` : "",
    resultado.family_name_alvo ? `family_name hipotético: ${resultado.family_name_alvo}` : "",
  ]
    .filter(Boolean)
    .join(" · ")
  const resumo =
    `${c.mlbs_ok || 0} MLB(s) lidos, ${c.familias || 0} família(s) atuais, ${c.isolados || 0} isolado(s).` +
    (cenario ? ` ${cenario}.` : "")
  const partes = [
    "# Validador de agrupamento",
    "",
    "_Somente GET_",
    "",
    `**${status}**`,
    "",
    resumo,
    "",
    mdTabela(
      ["Agrupáveis via API", "Se alterar parâmetro", "Já agrupados", "Bloqueados / isolados"],
      [[
        c.agrupaveis_api ?? 0,
        c.dependem_parametro ?? 0,
        c.ja_agrupados ?? 0,
        (c.bloqueados || 0) + (c.isolados || 0),
      ]]
    ),
    "",
  ]

  const avisos = [...(resultado.avisos || [])]
  for (const falha of resultado.falhas_get || []) {
    avisos.push(`GET ${falha.mlb || "?"}: ${falha.erro || "falha"}`)
  }
  if (avisos.length) {
    partes.push(`> ${avisos.join(" ")}`, "")
  }

  partes.push("## Oportunidades de agrupamento", "")
  const opps = resultado.oportunidades || []
  if (!opps.length) {
    partes.push("Nenhum produto no lote está partido em famílias distintas.", "")
  } else {
    for (const bloco of opps) partes.push(markdownCard(bloco))
  }

  partes.push("## Já na mesma família", "")
  const ja = resultado.ja_agrupados || []
  if (!ja.length) {
    partes.push("Nenhum grupo com family_id compartilhado neste lote.", "")
  } else {
    for (const bloco of ja) partes.push(markdownCard(bloco))
  }

  partes.push("## Famílias atuais", "")
  const familias = resultado.familias_atuais || []
  if (!familias.length) {
    partes.push("Nenhuma família neste lote.", "")
  } else {
    partes.push(
      mdTabela(
        ["Qtd", "family_name", "family_id", "Vendas", "Gênero", "LINE"],
        familias.map((bloco) => [
          bloco.n || 0,
          bloco.family_name || "",
          bloco.family_id || "—",
          bloco.vendas || 0,
          (bloco.gender || []).join(", "),
          (bloco.line || []).join(", "),
        ])
      ),
      ""
    )
  }

  partes.push("## Isolados no lote", "")
  const isolados = resultado.isolados || []
  if (!isolados.length) {
    partes.push("Nenhum isolado.", "")
  } else {
    for (const item of isolados) {
      partes.push(`- \`${item.mlb}\` · ${item.brand || "?"} ${item.model || "?"} · ${item.motivo || ""}`)
    }
    partes.push("")
  }

  partes.push("## Detalhe por MLB", "")
  const itens = resultado.itens || []
  if (!itens.length) {
    partes.push("Sem MLB (GET falhou ou lote vazio).", "")
  } else {
    partes.push(
      mdTabela(
        ["MLB", "Status", "Vendas", "GENDER", "LINE", "family_id", "family_name", "Veredicto"],
        itens.map((item) => [
          item.mlb || "",
          item.status || "—",
          item.vendas || 0,
          item.gender || "—",
          item.line || "—",
          item.family_id || "—",
          item.family_name || "—",
          rotuloVeredicto(item.veredicto),
        ])
      ),
      ""
    )
    partes.push("### Raio-x PARENT_PK / CHILD_PK", "")
    for (const item of itens) {
      const fmt = (mapa) =>
        Object.entries(mapa || {})
          .map(([chave, valor]) => `${chave}=${valor || "—"}`)
          .join(" · ")
      partes.push(`- \`${item.mlb}\``)
      partes.push(`  - PARENT_PK ${fmt(item.parent_pk)}`)
      partes.push(`  - CHILD_PK ${fmt(item.child_pk)}`)
    }
    partes.push("")
  }

  partes.push("## Texto completo", "", "```", resultado.texto || "(sem texto)", "```", "")
  return `${partes.join("\n").trim()}\n`
}

function htmlDivergencias(divergencias) {
  if (!divergencias || !divergencias.length) return ""
  const itens = divergencias.map((item) => {
    const valores = Object.entries(item.valores || {})
      .map(([valor, mlbs]) => `${valor} (${(mlbs || []).length})`)
      .join(" · ")
    return `<li><span class="text-zinc-500">${escapeHtml(item.campo)}</span> ${escapeHtml(valores)}</li>`
  })
  return `<ul class="mt-2 text-xs text-zinc-400 space-y-1">${itens.join("")}</ul>`
}

function htmlCardOportunidade(bloco) {
  const params = (bloco.parametros_a_alterar || []).join(", ") || "—"
  const bloqueios = (bloco.bloqueios || [])
    .map((texto) => `<li>${escapeHtml(texto)}</li>`)
    .join("")
  const familias = (bloco.familias || [])
    .map(
      (fam) =>
        `<li class="font-mono text-[11px] text-zinc-400">${fam.n} · ${escapeHtml(
          fam.family_name || "—"
        )} · id=${escapeHtml(fam.family_id || "—")} · vendas=${fam.vendas || 0}</li>`
    )
    .join("")
  const mlbs = (bloco.mlbs || []).slice(0, 8).join(" ")
  const extra = (bloco.mlbs || []).length > 8 ? ` +${(bloco.mlbs || []).length - 8}` : ""
  return `
    <article class="rounded-md border px-3 py-3 ${classeCard(bloco.via)}">
      <p class="text-[11px] uppercase tracking-wide text-acid">${escapeHtml(rotuloVia(bloco.via))}</p>
      <h4 class="text-sm font-semibold text-white mt-1">${escapeHtml(bloco.titulo || "")}</h4>
      <p class="text-xs text-zinc-300 mt-1">${escapeHtml(rotuloVeredicto(bloco.veredicto))}</p>
      <p class="text-sm text-zinc-300 mt-2">${escapeHtml(bloco.motivo || "")}</p>
      <p class="text-xs text-zinc-400 mt-2">Parâmetros a alterar: <span class="text-white">${escapeHtml(params)}</span></p>
      ${bloco.cenario_hipotetico ? `<p class="text-xs text-acid mt-2">${escapeHtml(bloco.cenario_hipotetico)}</p>` : ""}
      ${bloqueios ? `<ul class="mt-2 text-xs text-red-300 list-disc pl-4 space-y-1">${bloqueios}</ul>` : ""}
      <ul class="mt-2 space-y-0.5">${familias}</ul>
      ${htmlDivergencias(bloco.divergencias)}
      <p class="mt-2 font-mono text-[11px] text-zinc-500 break-all">${escapeHtml(mlbs)}${escapeHtml(extra)}</p>
    </article>
  `
}

function setBotoesExportacao(ativo) {
  const desligar = !ativo
  if (btnPdfValidador) btnPdfValidador.disabled = desligar
  if (btnMarkdownValidador) btnMarkdownValidador.disabled = desligar
}

function guardarValidacao(resultado) {
  ultimoResultadoValidacao = resultado
  try {
    if (resultado && resultado.ok !== false) {
      sessionStorage.setItem(VALIDACAO_KEY, JSON.stringify(resultado))
    } else {
      sessionStorage.removeItem(VALIDACAO_KEY)
    }
  } catch {
    sessionStorage.removeItem(VALIDACAO_KEY)
  }
}

function mostrarValidacao(resultado, trocarAba = true) {
  if (!resultado) return
  if (resultado.ok === false) {
    guardarValidacao(null)
    setBotoesExportacao(false)
    validadorVazio.classList.remove("hidden")
    validadorConteudo.classList.add("hidden")
    validadorVazio.textContent = resultado.error || "A validação não concluiu."
    if (trocarAba) ativarAba("validador")
    return
  }
  guardarValidacao(resultado)
  setBotoesExportacao(true)
  validadorVazio.classList.add("hidden")
  validadorConteudo.classList.remove("hidden")
  const c = resultado.contagens || {}
  validadorStatus.textContent = `${c.oportunidades || 0} oportunidade(s) · ${c.ja_agrupados || 0} já agrupado(s)`
  const cenario = [
    resultado.genero_alvo ? `GENDER hipotético: ${resultado.genero_alvo}` : "",
    resultado.family_name_alvo ? `family_name hipotético: ${resultado.family_name_alvo}` : "",
  ]
    .filter(Boolean)
    .join(" · ")
  validadorResumo.textContent =
    `${c.mlbs_ok || 0} MLB(s) lidos, ${c.familias || 0} família(s) atuais, ${c.isolados || 0} isolado(s).` +
    (cenario ? ` ${cenario}.` : "")

  validadorStats.innerHTML = [
    cardStat("Agrupáveis via API", c.agrupaveis_api),
    cardStat("Se alterar parâmetro", c.dependem_parametro),
    cardStat("Já agrupados", c.ja_agrupados),
    cardStat("Bloqueados / isolados", (c.bloqueados || 0) + (c.isolados || 0)),
  ].join("")

  const avisos = [...(resultado.avisos || [])]
  for (const falha of resultado.falhas_get || []) {
    avisos.push(`GET ${falha.mlb || "?"}: ${falha.erro || "falha"}`)
  }
  validadorAvisos.classList.toggle("hidden", avisos.length === 0)
  validadorAvisos.textContent = avisos.join(" ")

  const opps = resultado.oportunidades || []
  validadorOportunidades.innerHTML = opps.length
    ? opps.map(htmlCardOportunidade).join("")
    : '<p class="text-sm text-zinc-500">Nenhum produto no lote está partido em famílias distintas.</p>'

  const ja = resultado.ja_agrupados || []
  validadorJaAgrupados.innerHTML = ja.length
    ? ja.map(htmlCardOportunidade).join("")
    : '<p class="text-sm text-zinc-500">Nenhum grupo com family_id compartilhado neste lote.</p>'

  tabelaValidadorFamilias.innerHTML = ""
  const familias = resultado.familias_atuais || []
  if (!familias.length) {
    setCelulasVazias(tabelaValidadorFamilias, 6, "Nenhuma família neste lote.")
  }
  for (const bloco of familias) {
    const tr = document.createElement("tr")
    tr.className = "border-t border-line align-top"
    tr.innerHTML = `
      <td class="py-2 pr-3 font-mono text-acid">${bloco.n || 0}</td>
      <td class="py-2 pr-3 text-zinc-200">${escapeHtml(bloco.family_name || "")}</td>
      <td class="py-2 pr-3 font-mono text-[11px]">${escapeHtml(bloco.family_id || "—")}</td>
      <td class="py-2 pr-3 font-mono">${bloco.vendas || 0}</td>
      <td class="py-2 pr-3 text-zinc-400">${escapeHtml((bloco.gender || []).join(", "))}</td>
      <td class="py-2 text-zinc-400">${escapeHtml((bloco.line || []).join(", "))}</td>
    `
    tabelaValidadorFamilias.appendChild(tr)
  }

  listaIsolados.innerHTML = ""
  const isolados = resultado.isolados || []
  if (!isolados.length) {
    listaIsolados.innerHTML = '<li class="text-zinc-500">Nenhum isolado.</li>'
  }
  for (const item of isolados) {
    const li = document.createElement("li")
    li.textContent = `${item.mlb} · ${item.brand || "?"} ${item.model || "?"} · ${item.motivo || ""}`
    listaIsolados.appendChild(li)
  }

  tabelaValidadorMlbs.innerHTML = ""
  const mlbs = resultado.itens || []
  if (!mlbs.length) {
    setCelulasVazias(tabelaValidadorMlbs, 8, "Sem MLB (GET falhou ou lote vazio).")
  }
  for (const item of mlbs) {
    const tr = document.createElement("tr")
    tr.className = "border-t border-line align-top"
    tr.innerHTML = `
      <td class="py-2 pr-3 font-mono">${escapeHtml(item.mlb || "")}${htmlRaiox(item)}</td>
      <td class="py-2 pr-3">${escapeHtml(item.status || "—")}</td>
      <td class="py-2 pr-3 font-mono">${item.vendas || 0}</td>
      <td class="py-2 pr-3">${escapeHtml(item.gender || "—")}</td>
      <td class="py-2 pr-3">${escapeHtml(item.line || "—")}</td>
      <td class="py-2 pr-3 font-mono text-[11px]">${escapeHtml(item.family_id || "—")}</td>
      <td class="py-2 pr-3">${escapeHtml(item.family_name || "—")}</td>
      <td class="py-2">${escapeHtml(rotuloVeredicto(item.veredicto))}</td>
    `
    tabelaValidadorMlbs.appendChild(tr)
  }

  ultimoTextoValidador = resultado.texto || ""
  validadorTexto.textContent = ultimoTextoValidador || "(sem texto)"
  if (trocarAba) ativarAba("validador")
}

async function lerNdjson(resposta, onEvento) {
  const leitor = resposta.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { value, done } = await leitor.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const linhas = buffer.split("\n")
    buffer = linhas.pop() || ""
    for (const linha of linhas) {
      if (!linha.trim()) continue
      onEvento(JSON.parse(linha))
    }
  }
  if (buffer.trim()) onEvento(JSON.parse(buffer))
}

async function postStream(url, corpo, onDone, mensagemInicio) {
  if (contarEntrada(campoMlbs.value).total === 0) {
    adicionarLog({
      level: "error",
      message: "Cole pelo menos um MLB (ex.: MLB5152455691) ou SKU (ex.: 49566).",
      ts: new Date().toISOString(),
    })
    ativarAba("logs")
    return
  }
  if (chkLembrar.checked) sessionStorage.setItem(TOKEN_KEY, campoToken.value)
  else sessionStorage.removeItem(TOKEN_KEY)

  limparLogs()
  ativarAba("logs")
  setRodando(true)
  if (mensagemInicio) adicionarLog(mensagemInicio)

  try {
    const resposta = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    })
    if (!resposta.ok) {
      const detalhe = await resposta.json().catch(() => ({}))
      adicionarLog({
        level: "error",
        message: detalhe.detail || `HTTP ${resposta.status}`,
        ts: new Date().toISOString(),
      })
      return
    }
    await lerNdjson(resposta, (evento) => {
      if (evento.type === "log") adicionarLog(evento)
      if (evento.type === "done") onDone(evento.resultado)
    })
  } catch (erro) {
    adicionarLog({
      level: "error",
      message: String(erro),
      ts: new Date().toISOString(),
    })
  } finally {
    setRodando(false)
  }
}

async function executar(aplicar) {
  if (aplicar) {
    const ok = window.confirm(
      "Isso envia PUT reais no Mercado Livre. Continuar?"
    )
    if (!ok) return
  }
  await postStream("/api/executar", montarPedido(aplicar), mostrarResultado, {
    level: aplicar ? "warn" : "info",
    message: aplicar ? "Aplicar PUTs iniciado." : "Simulação iniciada.",
    ts: new Date().toISOString(),
  })
}

async function validarAgrupamento() {
  await postStream("/api/validar", montarPedido(false), mostrarValidacao, {
    level: "info",
    message: "Validador iniciado (somente GET).",
    ts: new Date().toISOString(),
  })
}

function baixarArquivo(url, nome) {
  const link = document.createElement("a")
  link.href = url
  link.download = nome
  link.rel = "noopener"
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function avisoValidador(mensagem, tipo = "ok") {
  if (!validadorAvisos) return
  validadorAvisos.classList.remove("hidden")
  validadorAvisos.classList.toggle("border-yellow-700/40", tipo !== "error")
  validadorAvisos.classList.toggle("bg-yellow-950/20", tipo !== "error")
  validadorAvisos.classList.toggle("text-yellow-200", tipo !== "error")
  validadorAvisos.classList.toggle("border-red-700/40", tipo === "error")
  validadorAvisos.classList.toggle("bg-red-950/20", tipo === "error")
  validadorAvisos.classList.toggle("text-red-200", tipo === "error")
  validadorAvisos.textContent = mensagem
}

function avisoPdfExportado(nome, url) {
  avisoValidador(`PDF exportado: ${nome}`)
  const separador = document.createTextNode(" ")
  const link = document.createElement("a")
  link.href = url
  link.download = nome
  link.className = "underline font-semibold"
  link.textContent = "Clique aqui se o download não iniciar."
  validadorAvisos.append(separador, link)
}

async function exportarPdfValidacao() {
  if (!ultimoResultadoValidacao || ultimoResultadoValidacao.ok === false) {
    avisoValidador("Rode uma validação antes de exportar o PDF.", "error")
    adicionarLog({
      level: "error",
      message: "Rode uma validação antes de exportar o PDF.",
      ts: new Date().toISOString(),
    })
    return
  }
  if (btnPdfValidador.disabled) return
  btnPdfValidador.textContent = "Gerando PDF…"
  btnPdfValidador.disabled = true
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 45000)
  try {
    const resposta = await fetch("/api/validar/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ultimoResultadoValidacao),
      signal: controller.signal,
    })
    const detalhe = await resposta.json().catch(() => ({}))
    if (!resposta.ok) {
      throw new Error(detalhe.detail || `HTTP ${resposta.status}`)
    }
    const nome = detalhe.nome || "validacao-agrupamento.pdf"
    const url = detalhe.url || `/api/relatorios/${encodeURIComponent(nome)}`
    baixarArquivo(url, nome)
    avisoPdfExportado(nome, url)
    adicionarLog({
      level: "ok",
      message: `PDF exportado: ${nome}`,
      ts: new Date().toISOString(),
    })
  } catch (erro) {
    const mensagem =
      erro.name === "AbortError"
        ? "Tempo esgotado ao gerar o PDF. Atualize a página (Ctrl+F5) e tente de novo."
        : String(erro)
    avisoValidador(mensagem, "error")
    adicionarLog({
      level: "error",
      message: mensagem,
      ts: new Date().toISOString(),
    })
  } finally {
    clearTimeout(timeoutId)
    btnPdfValidador.textContent = "Exportar PDF"
    setBotoesExportacao(Boolean(ultimoResultadoValidacao && ultimoResultadoValidacao.ok !== false))
  }
}

form.addEventListener("submit", (evento) => {
  evento.preventDefault()
  executar(false)
})

btnAplicar.addEventListener("click", () => executar(true))
btnValidar.addEventListener("click", () => validarAgrupamento())
btnLimpar.addEventListener("click", limparLogs)
tabLogs.addEventListener("click", () => ativarAba("logs"))
tabRelatorio.addEventListener("click", () => ativarAba("relatorio"))
tabValidador.addEventListener("click", () => ativarAba("validador"))
campoMlbs.addEventListener("input", atualizarContador)
btnVerToken.addEventListener("click", () => {
  const visivel = campoToken.type === "text"
  campoToken.type = visivel ? "password" : "text"
  btnVerToken.textContent = visivel ? "mostrar" : "ocultar"
})
btnCopiar.addEventListener("click", async () => {
  if (!ultimoTextoRelatorio) return
  await navigator.clipboard.writeText(ultimoTextoRelatorio)
  btnCopiar.textContent = "Copiado"
  setTimeout(() => {
    btnCopiar.textContent = "Copiar texto"
  }, 1500)
})
btnCopiarValidador.addEventListener("click", async () => {
  if (!ultimoTextoValidador) return
  await navigator.clipboard.writeText(ultimoTextoValidador)
  btnCopiarValidador.textContent = "Copiado"
  setTimeout(() => {
    btnCopiarValidador.textContent = "Copiar texto"
  }, 1500)
})
if (btnMarkdownValidador) {
  btnMarkdownValidador.addEventListener("click", async () => {
    if (!ultimoResultadoValidacao || ultimoResultadoValidacao.ok === false) {
      adicionarLog({
        level: "error",
        message: "Rode uma validação antes de copiar o Markdown.",
        ts: new Date().toISOString(),
      })
      return
    }
    await navigator.clipboard.writeText(markdownValidacao(ultimoResultadoValidacao))
    btnMarkdownValidador.textContent = "Copiado"
    setTimeout(() => {
      btnMarkdownValidador.textContent = "Copiar Markdown"
    }, 1500)
  })
}
if (btnPdfValidador) {
  btnPdfValidador.addEventListener("click", () => exportarPdfValidacao())
}

const tokenSalvo = sessionStorage.getItem(TOKEN_KEY)
if (tokenSalvo) {
  campoToken.value = tokenSalvo
  chkLembrar.checked = true
}
atualizarContador()
setBotoesExportacao(false)

try {
  const validacaoSalva = sessionStorage.getItem(VALIDACAO_KEY)
  if (validacaoSalva) {
    const parsed = JSON.parse(validacaoSalva)
    if (parsed && parsed.ok !== false) mostrarValidacao(parsed, false)
  }
} catch {
  sessionStorage.removeItem(VALIDACAO_KEY)
}
