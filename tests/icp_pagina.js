// Cofre Aberto MS — testa a aba Confiabilidade dos Dados (ICP) no painel: filtros, busca, detalhe da base, selos, celular.
// Uso: node tests/icp_pagina.js http://localhost:8000/
const { chromium, devices } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2] || "http://localhost:8000/";
const icp = JSON.parse(fs.readFileSync(__dirname + "/../dados/icp.json", "utf8"));
const bases = Object.values(icp.bases);
const norm = t => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
(async () => {
  const b = await chromium.launch();
  const res = [], err = [];
  const ok = (nome, cond, det) => res.push([cond, nome, det || ""]);
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  p.on("pageerror", e => err.push(e.message));
  await p.goto(BASE + "confiabilidade/"); await p.waitForTimeout(3500);
  ok("/confiabilidade/ abre a aba do painel", p.url().includes("#aba=confiabilidade"), p.url());
  ok("menu lateral visível", await p.isVisible(".sidebar nav button[data-tab='confiabilidade']"));
  ok("menu marca a aba ativa", await p.$eval(".sidebar nav button[data-tab='confiabilidade']", x => x.classList.contains("active")));
  ok("nota geral = icp.json", (await p.textContent("#icp-nota")).startsWith(String(icp.nota)), await p.textContent("#icp-nota"));
  const vis = () => p.$$eval("#tabela-icp tbody tr", r => r.filter(x => !x.hidden).length);
  ok("tabela lista todas as bases", (await vis()) === bases.length, `${await vis()} x ${bases.length}`);
  for (const st of Object.keys(icp.status).filter(k => bases.some(x => x.status === k))) {
    await p.click(`#icp-filtros [data-f="${st}"]`);
    const n = await vis(), esp = bases.filter(x => x.status === st).length;
    ok(`filtro '${st}'`, n === esp, `tela ${n} x dados ${esp}`);
  }
  await p.click('#icp-filtros [data-f=""]');
  await p.fill("#busca-icp", "camara");
  const nb = await vis(), espb = bases.filter(x => norm(x.nome + " " + x.orgao + " " + (x.fonteOficial || "")).includes("camara")).length;
  ok("busca 'camara' (sem acento)", nb === espb && nb > 0, `tela ${nb} x dados ${espb}`);
  await p.fill("#busca-icp", "");
  await p.click('#icp-cards [data-st="verificado"]');
  ok("cartão do painel filtra a tabela", (await vis()) === icp.indicadores.verificadas);
  await p.click('#icp-filtros [data-f=""]');
  // metodologia 2.0: tela = dados (nível e cobertura de cada base, resumo de cobertura no topo)
  const pctBR = v => (v > 0 && v < 1 ? v.toFixed(2) : String(Math.round(v * 10) / 10)).replace(".", ",") + "%";
  let evidOk = 0;
  for (const x of bases) {
    const txt = (await p.textContent(`#tabela-icp tr[data-id="${x.id}"] td[data-label="Evidência"]`)) || "";
    const c = x.cobertura;
    const esperado = !c ? "sem conferência" : !c.calculavel ? "não calculada" : pctBR(c.percentual);
    if (txt.includes(`Nível ${x.nivel}`) && txt.includes(esperado)) evidOk++;
    else ok(`evidência na tela de ${x.id}`, false, `tela "${txt.trim()}" x esperado nível ${x.nivel} · ${esperado}`);
  }
  ok("nível e cobertura na tabela = dados (24 bases)", evidOk === bases.length, `${evidOk}/${bases.length}`);
  const I = icp.indicadores;
  ok("topo mostra bases conferidas por inteiro, em parte e sem conferência = dados",
     (await p.textContent("#icp-abrangente")).trim() == String(I.conferenciaAbrangente) && (await p.textContent("#icp-parcial")).trim() == String(I.conferenciaParcial)
     && (await p.textContent("#icp-semconf")).trim() == String(I.semVerificacaoOficial) && (await p.textContent("#icp-criticos-n")).trim() == String(I.criticos));
  const cr = I.coberturaRegistros;
  ok("cobertura dos registros no topo = dados", (await p.textContent("#icp-cobertura")).trim() === (cr.percentualDoTotal == null ? "não calculada" : String(cr.percentualDoTotal).replace(".", ",") + "%"));
  ok("resumo explica o que a nota significa", (await p.textContent("#icp-resumo")).includes("conferidas por inteiro"));
  await p.click('#tabela-icp tr[data-id="shows"]'); await p.waitForTimeout(400);
  const dsh = await p.textContent("#icp-detalhe");
  ok("detalhe de base por amostra diz que nem todos os registros foram examinados", dsh.includes("Nem todos os registros foram examinados") && dsh.includes("Evidência que sustenta a nota"));
  await p.click('#tabela-icp tr[data-id="camara"]'); await p.waitForTimeout(400);
  const det = await p.textContent("#icp-detalhe");
  ok("clique abre o detalhe da base", det.includes(icp.bases.camara.nome));
  for (const s of ["Evidência que sustenta a nota", "Nível de evidência", "Transparência técnica", "Histórico de verificações", "Histórico de correções", "Limitações conhecidas", "Testes matemáticos", "Pendências"])
    ok(`detalhe tem '${s}'`, det.includes(s));
  // selo de outra aba abre o detalhe certo
  await p.goto(BASE + "cofre-aberto-ms.html#aba=governo-ms"); await p.waitForTimeout(3000);
  const selo = await p.$("#tab-governo-ms .selo-icp");
  ok("aba Governo MS mostra o selo do ICP", !!selo);
  if (selo) {
    ok("selo = status do ICP", (await selo.textContent()).includes(icp.bases["governo-ms"].statusRotulo));
    await selo.click(); await p.waitForTimeout(2500);
    ok("clique no selo abre o detalhe da base na aba do ICP", (await p.textContent("#icp-detalhe h2")) === icp.bases["governo-ms"].nome);
  }
  await p.goto(BASE + "cofre-aberto-ms.html#aba=emendas"); await p.waitForTimeout(3000);
  const se = await p.$("#tab-emendas .selo-icp");
  if (se && icp.bases.emendas.statusCor !== "verde") ok("base sem conferência na fonte não fica verde", !(await se.getAttribute("style")).includes("#1f9d6b"));
  await p.goto(BASE + "cofre-aberto-ms.html#aba=shows"); await p.waitForTimeout(3000);
  const ss = await p.$("#tab-shows .selo-icp");
  if (ss) {
    ok("selo de base conferida por amostra não é verde", !(await ss.getAttribute("style")).includes("#1f9d6b") || icp.bases.shows.nivel >= 3);
    ok("selo de base por amostra mostra o percentual conferido", icp.bases.shows.nivel !== 2 || (await ss.textContent()).includes("conferido"), await ss.textContent());
  }
  // link direto e link antigo
  const c = await b.newContext({ ...devices["iPhone 13"] });
  const m = await c.newPage();
  m.on("pageerror", e => err.push(e.message));
  await m.goto(BASE + "monitoramento/#camara-cg"); await m.waitForTimeout(4000);
  ok("link antigo /monitoramento/#camara-cg abre a Câmara no ICP", (await m.textContent("#icp-detalhe h2").catch(() => "")) === icp.bases.camara.nome, m.url());
  const [sw, cw] = await m.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  ok("celular sem rolagem horizontal na aba", sw <= cw + 1, `${sw} x ${cw}`);
  for (const id of Object.keys(icp.bases)) {
    await m.goto(BASE + `confiabilidade/${id}/`);
    const [a, bb] = await m.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    if (a > bb + 1) ok(`celular sem rolagem horizontal: /confiabilidade/${id}/`, false, `${a} x ${bb}`);
  }
  ok("páginas de base sem rolagem horizontal no celular", !res.some(r => !r[0] && r[1].startsWith("celular sem rolagem horizontal: /")));
  ok("sem erro de JavaScript", err.length === 0, err.join(" | "));
  for (const [c_, n, d] of res) console.log(c_ ? "✅" : "❌", n, d);
  const f = res.filter(r => !r[0]).length;
  console.log(`${res.length - f}/${res.length} OK`);
  await b.close();
  process.exit(f ? 1 : 0);
})();
