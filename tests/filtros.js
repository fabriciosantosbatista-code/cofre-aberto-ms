// Cofre Aberto MS — testa se filtros e buscas do painel devolvem o que os dados dizem.
// Uso: node tests/filtros.js http://localhost:8000/
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2] || "http://localhost:8000/";
const J = f => JSON.parse(fs.readFileSync(__dirname + "/../dados/" + f, "utf8"));
const norm = t => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const res = [], err = [];
  p.on("pageerror", e => err.push(e.message));
  const ok = (nome, cond, det) => res.push([cond, nome, det]);
  const abre = async aba => { await p.goto(BASE + "cofre-aberto-ms.html#aba=" + aba); await p.waitForTimeout(2500); };

  // Aluguéis: filtro Governo do Estado + busca
  const al = J("alugueis.json").pncp.lista;
  await abre("alugueis");
  await p.click('#al-filtros [data-f="E"]'); await p.waitForTimeout(300);
  let n = await p.$$eval("#tabela-al tbody tr", r => r.length);
  const nE = al.filter(c => c.esfera === "E").length;
  ok("Aluguéis: filtro Governo do Estado", n === Math.min(nE, 30), `tela ${n} x dados ${nE}`);
  await p.click('#al-filtros [data-f=""]'); await p.fill("#busca-al", "dourados"); await p.waitForTimeout(300);
  n = await p.$$eval("#tabela-al tbody tr", r => r.length);
  const nD = al.filter(c => norm([c.orgao, c.cidade, c.objeto, c.locador && c.locador.nome].join(" ")).includes("dourados")).length;
  ok("Aluguéis: busca 'dourados'", n === Math.min(nD, 30), `tela ${n} x dados ${nD}`);

  // Shows: clicar na 1ª cidade mostra os shows dela com o total certo
  const sh = J("shows.json");
  await abre("shows");
  const r0 = sh.ranking[0];
  await p.click("#tabela-sh-orgaos .sh-org-l"); await p.waitForTimeout(400);
  const chip = await p.$eval("#sh-local", e => e.textContent);
  const lst = r0.esfera === "E" ? sh.shows.filter(x => x.esfera === "E") : sh.shows.filter(x => x.esfera === "M" && x.cidadeOrgao === r0.nome);
  ok(`Shows: cidade "${r0.nome}" — quantidade no aviso`, chip.includes(`${lst.length} shows`), chip.slice(0, 80));
  const tot = Math.round(lst.reduce((s, x) => s + x.valor, 0)).toLocaleString("pt-BR");
  ok(`Shows: cidade "${r0.nome}" — total no aviso`, chip.replace(/\s/g, " ").includes(tot), `esperado R$ ${tot}`);

  // Produção legislativa: filtros dentro da tabela de Votos e projetos
  const pl = J("producao_legislativa.json").parlamentares.sort((a, b) => b.projetosPrincipal - a.projetosPrincipal)[0];
  await abre("votacoes");
  await p.click("#tabela-prod tr.prod-l"); await p.waitForTimeout(800);
  await p.click("#tabela-prod [data-f=lei]"); await p.waitForTimeout(200);
  n = await p.$$eval("#tabela-prod .prod-lista li", r => r.length);
  ok(`Produção ${pl.nome}: filtro 'viraram lei'`, n === Math.min(pl.leis, 15), `tela ${n} x dados ${pl.leis}`);

  // Busca global do topo
  await abre("panorama");
  await p.fill(".sidebar input[type=search], #busca-global, .sidebar input", "Camila"); await p.waitForTimeout(600);
  const achou = await p.evaluate(() => [...document.querySelectorAll("*")].some(e => e.childElementCount === 0 && /Camila Jara/.test(e.textContent) && e.offsetParent));
  ok("Busca global: 'Camila' encontra Camila Jara", achou, "");

  const falhas = res.filter(r => !r[0]);
  console.log(`✅ ${res.length - falhas.length} filtros/buscas certos · ❌ ${falhas.length} errados · erros JS: ${err.length}`);
  res.forEach(([c, nm, d]) => console.log(c ? "  ✓" : "  ❌", nm, d));
  err.forEach(e => console.log("  JS:", e));
  await b.close();
  process.exit(falhas.length || err.length ? 1 : 0);
})();
