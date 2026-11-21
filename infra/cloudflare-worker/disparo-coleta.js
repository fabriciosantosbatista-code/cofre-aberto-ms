// Cofre Aberto MS — disparo externo da coleta diária (Cloudflare Worker com Cron Trigger "37 4 * * *" = 00h37 de MS).
//
// O agendador do GitHub pula ou atrasa horas as execuções agendadas; este worker, fora do GitHub, dispara o workflow
// "Atualizar dados diariamente" uma vez por dia com origem "externo" (a coleta principal do dia, que não conta no limite
// de 2 coletas manuais). Os agendamentos do GitHub ficam como reserva e se encerram sozinhos se já houve coleta.
//
// Secret necessário no worker: GH_TOKEN = token fine-grained do GitHub, só do repositório cofre-aberto-ms, com
// "Actions: Read and write" (e Metadata: Read-only, automático). O token nunca aparece no código nem no log.
// Não há rota HTTP: o worker só roda pelo cron (ninguém consegue disparar a coleta abrindo um endereço).

const URL_DISPARO =
  "https://api.github.com/repos/fabriciosantosbatista-code/cofre-aberto-ms/actions/workflows/atualizar.yml/dispatches";

async function disparar(env) {
  for (let tentativa = 1; tentativa <= 3; tentativa++) {
    const r = await fetch(URL_DISPARO, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GH_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cofre-aberto-ms-disparo-externo",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { origem: "externo" } }),
    });
    if (r.status === 204) {
      console.log(`coleta disparada (tentativa ${tentativa})`);
      return;
    }
    // 401/403: token vencido, revogado ou sem permissão — não adianta repetir
    if (r.status === 401 || r.status === 403) {
      throw new Error(`GitHub recusou o token (${r.status}): renove o GH_TOKEN`);
    }
    console.log(`tentativa ${tentativa}: GitHub respondeu ${r.status}`);
    await new Promise((ok) => setTimeout(ok, 30000 * tentativa));
  }
  throw new Error("coleta não disparada depois de 3 tentativas");
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(disparar(env));
  },
};
