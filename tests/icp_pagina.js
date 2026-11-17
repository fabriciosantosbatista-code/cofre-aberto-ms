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
  await p.click('#tabela-icp tr[data-id="camara"]'); await p.waitForTimeout(400);
  const det = await p.textContent("#icp-detalhe");
  ok("clique abre o detalhe da base", det.includes(icp.bases.camara.nome));
  for (const s of ["Transparência técnica", "Histórico de verificações", "Histórico de correções", "Limitações conhecidas", "Testes matemáticos", "Pendências"])
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
