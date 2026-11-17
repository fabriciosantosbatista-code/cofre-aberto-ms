// Cofre Aberto MS — testa a página do ICP no navegador: filtros, busca, clique na base, selo do painel e celular.
// Uso: node tests/icp_pagina.js http://localhost:8000/
const { chromium, devices } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2] || "http://localhost:8000/";
const icp = JSON.parse(fs.readFileSync(__dirname + "/../dados/icp.json", "utf8"));
const bases = Object.values(icp.bases);
(async () => {
  const b = await chromium.launch();
  const res = [], err = [];
  const ok = (nome, cond, det) => res.push([cond, nome, det || ""]);
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  p.on("pageerror", e => err.push(e.message));
  await p.goto(BASE + "confiabilidade/");
  const vis = () => p.$$eval("#tab tbody tr", r => r.filter(x => !x.hidden).length);
  ok("tabela lista todas as bases", (await vis()) === bases.length, `${await vis()} x ${bases.length}`);
  for (const st of Object.keys(icp.status)) {
    await p.selectOption("#fstatus", st);
    const n = await vis(), esp = bases.filter(x => x.status === st).length;
    ok(`filtro de status '${st}'`, n === esp, `tela ${n} x dados ${esp}`);
  }
  await p.selectOption("#fstatus", "");
  await p.fill("#busca", "camara");
  const nb = await vis(), espb = bases.filter(x => (x.nome + " " + x.orgao + " " + (x.fonteOficial || "")).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").includes("camara")).length;
  ok("busca 'camara' (sem acento)", nb === espb && nb > 0, `tela ${nb} x dados ${espb}`);
  await p.fill("#busca", "");
  await p.click("#tab tbody tr.base >> nth=0");
  await p.waitForLoadState();
  ok("clique na linha abre a página da base", /\/confiabilidade\/[\w-]+\/$/.test(p.url()), p.url());
  ok("página da base mostra a transparência técnica", (await p.textContent("main")).includes("Transparência técnica"));
  // painel: selo ICP clicável na aba
  await p.goto(BASE + "cofre-aberto-ms.html#aba=governo-ms"); await p.waitForTimeout(3000);
  const selo = await p.$("#tab-governo-ms .selo-icp");
  ok("painel mostra o selo do ICP", !!selo);
  if (selo) {
    const t = await selo.textContent(), h = await selo.getAttribute("href");
    ok("selo do painel = status do ICP", t.includes(icp.bases["governo-ms"].statusRotulo), t);
    ok("selo leva à página da base", h === "/confiabilidade/governo-ms/", h);
  }
  await p.goto(BASE + "cofre-aberto-ms.html#aba=emendas"); await p.waitForTimeout(3000);
  const se = await p.$("#tab-emendas .selo-icp");
  if (se) ok("base sem conferência na fonte não fica verde", !(await se.getAttribute("style")).includes("#1f9d6b") || icp.bases.emendas.statusCor === "verde");
  // celular: sem rolagem horizontal
  const c = await b.newContext({ ...devices["iPhone 13"] });
  const m = await c.newPage();
  for (const u of ["confiabilidade/", ...Object.keys(icp.bases).map(k => `confiabilidade/${k}/`)]) {
    await m.goto(BASE + u);
    const [sw, cw] = await m.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    ok(`celular sem rolagem horizontal: /${u}`, sw <= cw + 1, `${sw} x ${cw}`);
  }
  await m.goto(BASE + "monitoramento/#camara-cg"); await m.waitForTimeout(1500);
  ok("link antigo /monitoramento/#camara-cg leva à Câmara no ICP", m.url().includes("/confiabilidade/camara/"), m.url());
  ok("sem erro de JavaScript", err.length === 0, err.join(" | "));
  for (const [c_, n, d] of res) console.log(c_ ? "✅" : "❌", n, d);
  const f = res.filter(r => !r[0]).length;
  console.log(`${res.length - f}/${res.length} OK`);
  await b.close();
  process.exit(f ? 1 : 0);
})();
