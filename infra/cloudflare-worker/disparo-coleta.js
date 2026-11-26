// Cofre Aberto MS — disparos externos (Cloudflare Worker "cofre-disparo-coleta", com 2 Cron Triggers).
//
// O agendador do GitHub pula ou atrasa horas as execuções agendadas (em 25/11/2026 o Instagram das 11h47 rodou 8 h
// atrasado); este worker, fora do GitHub, dispara os workflows na hora certa com origem "externo". Os agendamentos do
// GitHub ficam como reserva e se encerram sozinhos se o disparo externo já fez o trabalho.
//
// Cada cron dispara um workflow (a Cloudflare informa qual cron disparou em event.cron, exatamente como cadastrado):
//   "37 4 * * *"   → atualizar.yml  (coleta diária)          04h37 UTC = 00h37 de Campo Grande
//   "47 15 * * *"  → instagram.yml  (post do dia + story)     15h47 UTC = 11h47 de Campo Grande
// Cron que não está na lista: nada é disparado e o erro aparece no log do worker.
//
// Secret necessário no worker: GH_TOKEN = token fine-grained do GitHub, só do repositório cofre-aberto-ms, com
// "Actions: Read and write" (e Metadata: Read-only, automático) — vale para os dois workflows. O token nunca aparece
// no código nem no log. Não há rota HTTP: o worker só roda pelos crons (ninguém consegue disparar abrindo um endereço).

const REPO = "https://api.github.com/repos/fabriciosantosbatista-code/cofre-aberto-ms/actions/workflows/";

const DISPAROS = {
  "37 4 * * *": { workflow: "atualizar.yml", nome: "coleta" },
  "47 15 * * *": { workflow: "instagram.yml", nome: "Instagram" },
};

async function disparar(env, alvo) {
  for (let tentativa = 1; tentativa <= 3; tentativa++) {
    const r = await fetch(REPO + alvo.workflow + "/dispatches", {
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
      console.log(`${alvo.nome} disparado (${alvo.workflow}, tentativa ${tentativa})`);
      return;
    }
    // 401/403: token vencido, revogado ou sem permissão — não adianta repetir
    if (r.status === 401 || r.status === 403) {
      throw new Error(`${alvo.nome}: GitHub recusou o token (${r.status}) — renove o GH_TOKEN`);
    }
    // 422: o workflow não aceita a entrada "origem" (ou não tem workflow_dispatch) — não adianta repetir
    if (r.status === 422) {
      throw new Error(`${alvo.nome}: GitHub recusou o disparo (422): ${(await r.text()).slice(0, 200)}`);
    }
    console.log(`${alvo.nome}, tentativa ${tentativa}: GitHub respondeu ${r.status}`);
    await new Promise((ok) => setTimeout(ok, 30000 * tentativa));
  }
  throw new Error(`${alvo.nome} não disparado depois de 3 tentativas`);
}

export default {
  async scheduled(event, env, ctx) {
    const alvo = DISPAROS[event.cron];
    if (!alvo) {
      throw new Error(`cron "${event.cron}" sem workflow associado — nada disparado (veja DISPAROS)`);
    }
    ctx.waitUntil(disparar(env, alvo));
  },
};
