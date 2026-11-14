/* Cofre Aberto MS — Impostômetro: impostos pagos ao Governo de MS e à Prefeitura de Campo Grande no ano.
   Os valores por mês são oficiais (Tesouro Nacional, Siconfi — RREO Anexo 3). O número "ao vivo" é uma ESTIMATIVA:
   o total oficial até o último mês publicado + o ritmo médio dos últimos 12 meses desde então. */
(function () {
  const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

  function ente(e, agora) {
    const ano = agora.getFullYear();
    const ks = Object.keys(e.meses).sort();
    const ult = e.ultimoMes;
    const [ua, um] = ult.split("-").map(Number);
    const doze = ks.filter(k => k <= ult).slice(-12);
    const soma12 = doze.reduce((s, k) => s + (e.meses[k].impostos || 0), 0);
    const ritmo = soma12 / (365.25 * 86400);  // R$ por segundo, média dos últimos 12 meses
    let oficial = 0, base;
    if (ua === ano) {
      oficial = ks.filter(k => k.startsWith(ano + "-") && k <= ult).reduce((s, k) => s + (e.meses[k].impostos || 0), 0);
      base = new Date(ano, um, 1);        // fim do último mês publicado
    } else {
      base = new Date(ano, 0, 1);         // virou o ano e ainda não há mês publicado
    }
    const anterior = ks.filter(k => k.startsWith((ano - 1) + "-") && Number(k.slice(5)) <= (ua === ano ? um : 0))
      .reduce((s, k) => s + (e.meses[k].impostos || 0), 0);
    return { oficial, base, ritmo, ultimoMes: ult, rotuloMes: `${MESES[um - 1]}/${ua}`, anterior, ano,
             valor: t => oficial + Math.max(0, (t - base) / 1000) * ritmo };
  }

  window.Arrecadometro = {
    MESES,
    calcular(dados, agora = new Date()) {
      const es = dados.entes.estado ? ente(dados.entes.estado, agora) : null;
      const cg = dados.entes.cg ? ente(dados.entes.cg, agora) : null;
      return { estado: es, cg, ritmo: (es ? es.ritmo : 0) + (cg ? cg.ritmo : 0),
               valor: t => (es ? es.valor(t) : 0) + (cg ? cg.valor(t) : 0) };
    },
    formatar(v) { return "R$ " + Math.floor(v).toLocaleString("pt-BR"); },
    /* liga um contador a elementos: {total, estado, cg} (ids) */
    animar(calc, ids) {
      const els = Object.fromEntries(Object.entries(ids).map(([k, id]) => [k, document.getElementById(id)]).filter(([, el]) => el));
      const passo = () => {
        const t = Date.now();
        if (els.total) els.total.textContent = this.formatar(calc.valor(t));
        if (els.estado && calc.estado) els.estado.textContent = this.formatar(calc.estado.valor(t));
        if (els.cg && calc.cg) els.cg.textContent = this.formatar(calc.cg.valor(t));
      };
      passo();
      return setInterval(passo, 100);
    },
  };
})();
