// Cofre Aberto MS — confere se os números mostrados no painel são os mesmos dos arquivos de dados.
// Recalcula cada número a partir do JSON (independente do código do painel) e compara com o texto na tela.
// Uso: node tests/tela_x_dados.js http://localhost:8000/
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2] || "http://localhost:8000/";
const J = f => JSON.parse(fs.readFileSync(__dirname + "/../dados/" + f, "utf8"));
const num = t => { // "R$ 21,2 bi" / "R$ 1.234,56" / "2.450" → número (ou intervalo para compactos)
  t = (t || "").replace(/\s+/g, " ").trim();
  const m = t.match(/(-?[\d.]+(?:,\d+)?)\s*(milhões|milhão|mil|mi|bilhões|bilhão|bi)?/i);
  if (!m) return null;
  let v = parseFloat(m[1].replace(/\./g, "").replace(",", "."));
  const u = (m[2] || "").toLowerCase();
  const mult = u.startsWith("bi") ? 1e9 : u.startsWith("mi") && u !== "mil" ? 1e6 : u === "mil" ? 1e3 : 1;
  const casas = (m[1].split(",")[1] || "").length;
  return { v: v * mult, tol: mult > 1 ? 0.5 * Math.pow(10, -casas) * mult + 1 : 0.011 };
};
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const erros = [], oks = [];
  p.on("pageerror", e => erros.push("JS: " + e.message));
  const confere = async (aba, sel, esperado, rotulo) => {
    await p.goto(BASE + "cofre-aberto-ms.html#aba=" + aba);
    await p.waitForFunction(s => { const e = document.querySelector(s); return e && /\d/.test(e.textContent); }, sel, { timeout: 20000 }).catch(() => {});
    const t = await p.$eval(sel, e => e.textContent).catch(() => null);
    const n = num(t);
    if (!n) { erros.push(`${rotulo}: tela sem número ("${t}")`); return; }
    if (Math.abs(n.v - esperado) <= n.tol) oks.push(`${rotulo}: "${t.trim()}" ✓`);
    else erros.push(`${rotulo}: tela "${t.trim()}" (${n.v.toLocaleString("pt-BR")}) x dados ${esperado.toLocaleString("pt-BR")}`);
  };
  const soma = a => a.reduce((s, x) => s + (x || 0), 0);
  const fed = J("deputados_federais_ms.json").deputados;
  await confere("deputados", "#dep-total", soma(fed.map(d => d.cotaGastaAno)), "Dep. federais MS: total CEAP");
  const gov = J("governo_ms.json");
  await confere("governo-ms", "#gov-total", soma(gov.orgaos.map(o => o.pago)), "Governo MS: pago (soma dos órgãos)");
  const pf = J("prefeitura.json");
  await confere("prefeitura", "#pref-total", soma(pf.despesas.map(r => r.valor)), "Prefeitura CG: pago (soma das despesas)");
  const sh = J("shows.json");
  await confere("shows", "#sh-total", soma(sh.shows.map(x => x.valor)), "Shows: total (soma dos shows)");
  await confere("shows", "#sh-n", sh.shows.length, "Shows: quantidade");
  const al = J("alugueis.json");
  await confere("alugueis", "#al-total", soma(al.pncp.lista.map(c => c.valor)), "Aluguéis: contratos PNCP");
  await confere("alugueis", "#al-pref", soma(al.prefeitura.lista.map(a => a.valor)), "Aluguéis: Prefeitura CG");
  const bf = J("beneficios_fiscais.json");
  await confere("beneficios", "#bf-total", bf.total, "Benefícios: empresas");
  await confere("beneficios", "#bf-caso", bf.empresas.length, "Benefícios: caso a caso (lista)");
  const em = J("emendas_municipios.json");
  await confere("emendas", "#em-pagamentos", em.pagamentos, "Emendas: pagamentos");
  const ss = J("supersalarios.json");
  await confere("supersalarios", "#ss-liquido", ss.liquidoAcimaTeto, "Supersalários: líquido acima do teto");
  await confere("supersalarios", "#ss-bruto", ss.acimaTeto, "Supersalários: bruto acima do teto");
  await confere("supersalarios", "#ss-pessoas", ss.totalPessoas, "Supersalários: contracheques analisados");
  const ob = J("obras.json");
  await confere("obras", "#ob-n", ob.comProblema.obras, "Obras: com sinal");
  const cm = J("camara_municipal.json");
  await confere("camara", "#tab-camara .hero-number", soma(cm.vereadores.map(v => (v.gabinete || {}).gastoPessoalMensal)), "Câmara CG: pessoal dos gabinetes no mês (soma dos 29)");
  console.log(`✅ ${oks.length} números iguais · ❌ ${erros.length} diferentes`);
  oks.forEach(x => console.log("  ✓", x)); erros.forEach(x => console.log("  ❌", x));
  await b.close();
  process.exit(erros.length ? 1 : 0);
})();
