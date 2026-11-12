#!/usr/bin/env node
/*
 * Cofre Aberto MS — teste de fumaça do site (roda no GitHub Actions)
 *
 * Abre a capa, as páginas estáticas e todas as abas do painel, clica em
 * cada vereador, deputado estadual, senador e deputado federal de MS (e em
 * amostras das listas nacionais e das câmaras do interior) e falha se
 * encontrar erro de JavaScript, "NaN"/"undefined" na tela, detalhe que não
 * abre ou rolagem horizontal no celular.
 *
 * Exemplo de bug que este teste teria pegado: em nov/2026, 5 deputados
 * estaduais sem "id" no JSON não abriam ao clicar (erro "reading 'gabinete'").
 *
 * Uso:  node tests/smoke.js http://localhost:8000/
 */
const { chromium } = require("playwright");

const BASE = (process.argv[2] || "http://localhost:8000/").replace(/\/?$/, "/");
const BAD = /\bNaN\b|\bundefined\b|\[object Object\]|\bInfinity\b/g;
const TODOS = ["deputados", "senadores", "camara", "deputados-estaduais"];      // clica em todos os itens
const AMOSTRA = ["prefeitura", "judiciario", "deputados-brasil", "senado-brasil", "conexoes", "emendas", "supersalarios"]; // clica em alguns
const PAGINAS = ["", "press.html", "metodologia.html", "vereadores-campo-grande.html", "deputados-estaduais-ms.html", "senadores-ms.html",
  "vereador/", "deputado-estadual/", "deputado-federal/", "senador/",
  "vereador/papy/", "deputado-estadual/zeca-do-pt/", "deputado-federal/geraldo-resende/", "senador/tereza-cristina/",
  "empresa/", "empresa/34028316/", "empresa/29376294/", "boletim/", "orgao/", "orgao/tjms/", "orgao/tce-ms/", "orgao/governo-sefaz/"];

const problemas = [];
const falha = (msg) => { problemas.push(msg); console.log("  ❌ " + msg); };

(async () => {
  const browser = await chromium.launch();
  for (const [nome, viewport] of [["desktop", { width: 1366, height: 900 }], ["mobile", { width: 375, height: 812 }]]) {
    console.log(`\n=== ${nome} (${viewport.width}px)`);
    const page = await browser.newPage({ viewport });
    let onde = "";
    page.on("pageerror", (e) => falha(`[${nome}] erro de JavaScript em ${onde}: ${e.message}`));

    // ---- páginas estáticas ----
    for (const pg of PAGINAS) {
      onde = pg || "index.html";
      const resp = await page.goto(BASE + pg, { waitUntil: "load" });
      if (!resp || resp.status() >= 400) { falha(`[${nome}] ${onde} respondeu ${resp && resp.status()}`); continue; }
      await page.waitForTimeout(800);
      const r = await page.evaluate(() => ({ tx: document.body.innerText, ovX: document.documentElement.scrollWidth - innerWidth }));
      const m = r.tx.match(BAD);
      if (m) falha(`[${nome}] ${onde} mostra ${[...new Set(m)]}`);
      if (r.ovX > 1) falha(`[${nome}] ${onde} tem rolagem horizontal (${r.ovX}px)`);
    }
    // selo de data da capa deve estar dentro do layout
    await page.goto(BASE, { waitUntil: "load" });
    await page.waitForTimeout(800);
    const selo = await page.evaluate(() => {
      const b = document.querySelector(".hero-badge"), t = document.getElementById("data-atualizacao");
      if (!b || !t) return null;
      const bb = b.getBoundingClientRect(), tb = t.getBoundingClientRect();
      return { dentro: tb.left >= bb.left - 1 && tb.right <= bb.right + 1 && tb.width > 30, texto: t.textContent };
    });
    if (!selo) falha(`[${nome}] capa sem o selo "Dados atualizados"`);
    else if (!selo.dentro) falha(`[${nome}] data do selo "Dados atualizados" fora do layout`);
    else console.log(`  ✅ capa — dados atualizados em ${selo.texto}`);

    // ---- painel ----
    onde = "painel (carregamento)";
    await page.goto(BASE + "cofre-aberto-ms.html", { waitUntil: "load" });
    await page.waitForTimeout(6000);

    for (const tab of [...TODOS, ...AMOSTRA]) {
      onde = `aba ${tab}`;
      await page.locator(`button[data-tab="${tab}"]`).evaluate((e) => e.click());
      await page.waitForTimeout(2500);
      const info = await page.evaluate((t) => {
        const el = document.getElementById("tab-" + t);
        return el ? { tx: el.innerText, linhas: el.querySelectorAll("tr.clickable").length,
                      ovX: document.documentElement.scrollWidth - innerWidth } : null;
      }, tab);
      if (!info) { falha(`[${nome}] aba ${tab} não existe`); continue; }
      const m = info.tx.match(BAD);
      if (m) falha(`[${nome}] aba ${tab} mostra ${[...new Set(m)]}`);
      if (info.ovX > 1) falha(`[${nome}] aba ${tab} tem rolagem horizontal (${info.ovX}px)`);
      if (!info.linhas) { falha(`[${nome}] aba ${tab} sem nenhum item na lista`); continue; }

      const n = info.linhas;
      const idxs = TODOS.includes(tab) ? [...Array(n).keys()]
        : [...new Set([0, 1, Math.floor(n / 2), n - 1])];
      let abertos = 0;
      for (const i of idxs) {
        onde = `aba ${tab}, item ${i + 1}`;
        await page.locator(`#tab-${tab} tr.clickable`).nth(i).evaluate((e) => e.click());
        // partes do detalhe vêm de APIs ao vivo (ex.: dados pessoais do Senado):
        // espera até 15 s o "Carregando…" sumir antes de avaliar
        let d = null;
        for (let k = 0; k < 30; k++) {
          await page.waitForTimeout(500);
          d = await page.evaluate((t) => {
            const p = [...document.querySelectorAll(`#tab-${t} .detail-panel`)].find((x) => x.classList.contains("active"));
            return p ? { h: (p.querySelector("h3") || {}).innerText || "", tx: p.innerText } : null;
          }, tab);
          if (d && d.tx.length >= 50 && !/Carregando/.test(d.tx)) break;
        }
        if (!d || d.tx.length < 50) { falha(`[${nome}] ${onde}: detalhe não abriu`); continue; }
        const mm = d.tx.match(BAD);
        if (mm) falha(`[${nome}] ${onde} (${d.h}): mostra ${[...new Set(mm)]}`);
        if (/Carregando/.test(d.tx)) falha(`[${nome}] ${onde} (${d.h}): ficou em "Carregando"`);
        abertos++;
      }
      console.log(`  ✅ ${tab}: ${n} itens, ${abertos}/${idxs.length} detalhes abertos`);
    }

    // abas de tabelas (sem detalhe por clique): Contratos CG e Governo MS
    for (const [tab, tabelas] of [["contratos-cg", ["ranking-ct-forn", "tabela-ct-contratos", "tabela-ct-licit"]],
                                  ["governo-ms", ["ranking-gov-credores", "tabela-gov-escalao", "tabela-gov-diarias", "tabela-diarias-comp"]]]) {
      onde = `aba ${tab}`;
      await page.locator(`button[data-tab="${tab}"]`).evaluate((e) => e.click());
      await page.waitForTimeout(3000);
      const info = await page.evaluate(([t, ids]) => ({
        tx: document.getElementById("tab-" + t).innerText,
        ovX: document.documentElement.scrollWidth - innerWidth,
        hero: (document.querySelector(`#tab-${t} .hero-number`) || {}).innerText,
        linhas: ids.map((id) => document.querySelectorAll(`#${id} tbody tr`).length),
      }), [tab, tabelas]);
      const m = info.tx.match(BAD);
      if (m) falha(`[${nome}] aba ${tab} mostra ${[...new Set(m)]}`);
      if (info.ovX > 1) falha(`[${nome}] aba ${tab} tem rolagem horizontal (${info.ovX}px)`);
      if (!info.hero || /—/.test(info.hero)) falha(`[${nome}] aba ${tab}: total do topo vazio`);
      info.linhas.forEach((n, i) => { if (n < 2) falha(`[${nome}] aba ${tab}: tabela ${tabelas[i]} com ${n} linhas`); });
      console.log(`  ✅ ${tab}: ${info.hero} · linhas ${info.linhas.join("/")}`);
    }

    // pontos de atenção (Contratos CG) e servidores da ALEMS (aba de deputados estaduais)
    onde = "pontos de atenção";
    await page.locator('button[data-tab="contratos-cg"]').evaluate((e) => e.click());
    await page.waitForTimeout(1500);
    const nAlertas = await page.locator("#ct-alertas .alerta-card").count();
    if (nAlertas < 1) falha(`[${nome}] Contratos CG: nenhum ponto de atenção`);
    onde = "servidores da ALEMS";
    await page.locator('button[data-tab="deputados-estaduais"]').evaluate((e) => e.click());
    await page.waitForTimeout(2000);
    const al = await page.evaluate(() => ({ n: document.querySelectorAll("#tabela-alems tbody tr").length,
      tx: document.getElementById("alems-servidores").innerText, ovX: document.documentElement.scrollWidth - innerWidth }));
    if (al.n < 10) falha(`[${nome}] servidores da ALEMS: tabela com ${al.n} linhas`);
    if (BAD.test(al.tx)) falha(`[${nome}] servidores da ALEMS mostram ${al.tx.match(BAD)}`);
    if (al.ovX > 1) falha(`[${nome}] servidores da ALEMS: rolagem horizontal (${al.ovX}px)`);
    console.log(`  ✅ pontos de atenção: ${nAlertas} · servidores ALEMS: ${al.n} linhas`);
    onde = "auditoria";
    await page.locator('button[data-tab="auditoria"]').evaluate((e) => e.click());
    await page.waitForTimeout(1500);
    const au = await page.evaluate(() => ({ n: document.querySelectorAll("#au-sinais .alerta-card").length,
      p: document.querySelectorAll("#tabela-au-placar tbody tr").length,
      tx: document.getElementById("tab-auditoria").innerText, ovX: document.documentElement.scrollWidth - innerWidth }));
    if (au.n < 1) falha(`[${nome}] Auditoria: nenhum sinal na lista`);
    if (BAD.test(au.tx)) falha(`[${nome}] Auditoria mostra ${au.tx.match(BAD)}`);
    if (au.ovX > 1) falha(`[${nome}] Auditoria: rolagem horizontal (${au.ovX}px)`);
    console.log(`  ✅ auditoria: ${au.n} sinais na tela · placar com ${au.p} linhas`);
    // abas sem lista clicável: conferem se as tabelas principais têm linhas e se não há NaN/undefined
    const tabelasPorAba = { presidencia: ["tabela-pr-cartao", "tabela-pr-unidades", "tabela-pr-orc", "tabela-pr-rem", "tabela-pr-mun"],
      stf: ["tabela-stf-min", "tabela-stf-ult", "tabela-stf-comp"], "governo-ms": ["tabela-gov-contratos", "tabela-gov-lic"] };
    for (const [aba, ids] of Object.entries(tabelasPorAba)) {
      onde = aba;
      await page.locator(`button[data-tab="${aba}"]`).evaluate((e) => e.click());
      await page.waitForTimeout(3000);
      const r = await page.evaluate(([a, ids]) => ({ n: ids.map((i) => document.querySelectorAll(`#${i} tbody tr`).length),
        tx: document.getElementById("tab-" + a).innerText, ovX: document.documentElement.scrollWidth - innerWidth }), [aba, ids]);
      r.n.forEach((n, i) => { if (n < 1) falha(`[${nome}] ${aba}: tabela ${ids[i]} vazia`); });
      if (BAD.test(r.tx)) falha(`[${nome}] ${aba} mostra ${r.tx.match(BAD)}`);
      if (r.ovX > 1) falha(`[${nome}] ${aba}: rolagem horizontal (${r.ovX}px)`);
      console.log(`  ✅ ${aba}: linhas ${r.n.join("/")}`);
    }

    // evolução: os 4 grupos têm gráfico e ranking; clicar num parlamentar troca o gráfico
    onde = "aba evolucao";
    await page.locator('button[data-tab="evolucao"]').evaluate((e) => e.click());
    await page.waitForTimeout(2000);
    for (const g of ["estadual", "federal", "senador", "vereador"]) {
      onde = `aba evolucao, grupo ${g}`;
      await page.locator(`.ev-grupos button[data-grupo="${g}"]`).evaluate((e) => e.click());
      await page.waitForTimeout(500);
      const r = await page.evaluate(() => ({
        linhas: document.querySelectorAll("#ranking-ev tbody tr.clickable").length,
        svg: !!document.querySelector("#ev-chart svg polyline"),
        tx: document.getElementById("tab-evolucao").innerText,
      }));
      if (!r.svg) falha(`[${nome}] evolução ${g}: gráfico não desenhou`);
      if (!r.linhas) falha(`[${nome}] evolução ${g}: ranking vazio`);
      const mm = r.tx.match(BAD);
      if (mm) falha(`[${nome}] evolução ${g}: mostra ${[...new Set(mm)]}`);
      await page.locator("#ranking-ev tr.clickable").first().evaluate((e) => e.click());
      await page.waitForTimeout(400);
      if (!(await page.isVisible("#ev-voltar"))) falha(`[${nome}] evolução ${g}: clique no parlamentar não abriu o gráfico dele`);
    }
    console.log("  ✅ evolução: 4 grupos com gráfico e ranking");

    // link direto (#aba=...&p=...) abre o parlamentar
    onde = "link direto";
    await page.goto(BASE + "cofre-aberto-ms.html#aba=deputados-estaduais&p=Zeca%20do%20PT", { waitUntil: "load" });
    await page.waitForTimeout(6000);
    const aberto = await page.evaluate(() => document.querySelector("#tab-deputados-estaduais .detail-panel.active h3")?.textContent || "");
    if (aberto !== "Zeca do PT") falha(`[${nome}] link direto #aba=deputados-estaduais&p=Zeca do PT abriu "${aberto || "nada"}"`);
    else console.log("  ✅ link direto abre o parlamentar");
    if (!(await page.$("#tab-deputados-estaduais .detail-panel.active .seguir-btn"))) falha(`[${nome}] botão "Seguir notas novas" não apareceu`);
    await page.goto(BASE + "cofre-aberto-ms.html", { waitUntil: "load" });
    await page.waitForTimeout(4000);

    // câmaras do interior: todas
    onde = "aba camaras-ms";
    await page.locator('button[data-tab="camaras-ms"]').evaluate((e) => e.click());
    await page.waitForTimeout(1500);
    const cards = await page.locator("#grid-camaras-ms .card.clickable").count();
    for (let i = 0; i < cards; i++) {
      onde = `câmara do interior ${i + 1}`;
      await page.locator("#grid-camaras-ms .card.clickable").nth(i).evaluate((e) => e.click());
      await page.waitForTimeout(1200);
      const tx = await page.textContent("#detail-camara-cidade");
      const mm = tx.match(BAD);
      if (mm) falha(`[${nome}] ${onde}: mostra ${[...new Set(mm)]}`);
      if (/indisponíveis no momento/.test(tx)) falha(`[${nome}] ${onde}: JSON não carregou`);
    }
    console.log(`  ✅ câmaras do interior: ${cards} abertas`);

    // busca global
    onde = "busca global";
    await page.evaluate(() => {
      const i = document.getElementById("busca-global");
      i.value = "Trad"; i.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await page.waitForTimeout(1200);
    const achou = await page.evaluate(() => [...document.querySelectorAll("body *")]
      .some((e) => e.offsetParent && /absolute|fixed/.test(getComputedStyle(e).position) && /Trad/.test(e.innerText)));
    if (!achou) falha(`[${nome}] busca global por "Trad" não mostrou resultados`);
    else console.log("  ✅ busca global");
    await page.close();
  }
  await browser.close();

  console.log(problemas.length ? `\n❌ ${problemas.length} problema(s) encontrado(s)` : "\n✅ Site OK — nenhum problema encontrado");
  process.exit(problemas.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
