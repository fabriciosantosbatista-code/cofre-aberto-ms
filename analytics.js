/* Cofre Aberto MS — aviso de cookies do Google Analytics (LGPD, Modo de consentimento do Google).
   A tag do GA (G-D3SHQ303HR) fica no <head> de cada página com o consentimento "negado" por padrão:
   assim o Google só recebe sinais anônimos, sem cookies. Este arquivo mostra o aviso e, se o visitante
   aceitar, libera os cookies de análise (consent update). A escolha fica guardada no navegador. */
(function () {
  var CHAVE = "cofre-cookies";
  function ler() { try { return localStorage.getItem(CHAVE); } catch (e) { return null; } }
  function gravar(v) { try { localStorage.setItem(CHAVE, v); } catch (e) {} }
  function liberar() { if (window.gtag) gtag("consent", "update", { analytics_storage: "granted" }); }
  var escolha = ler();
  if (escolha === "sim") return liberar();
  if (escolha === "nao") return;
  function aviso() {
    var d = document.createElement("div");
    d.setAttribute("role", "dialog"); d.setAttribute("aria-label", "Aviso de cookies");
    d.style.cssText = "position:fixed;left:16px;right:16px;bottom:16px;z-index:9999;max-width:560px;margin:0 auto;background:#161a23;color:#f0f3fa;" +
      "border:1px solid #232839;border-radius:12px;padding:14px 16px;font:14px/1.5 Inter,system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.5)";
    d.innerHTML = "Usamos cookies do Google Analytics só para contar visitas e saber quais páginas são mais úteis. Nenhum dado é vendido. " +
      "<a href='/metodologia.html#privacidade' style='color:#f5c842'>Saiba mais</a>" +
      "<div style='display:flex;gap:8px;margin-top:10px;justify-content:flex-end'>" +
      "<button data-c='nao' style='background:none;border:1px solid #232839;color:#8b95aa;border-radius:999px;padding:7px 14px;cursor:pointer'>Recusar</button>" +
      "<button data-c='sim' style='background:#f5c842;border:0;color:#14120a;font-weight:600;border-radius:999px;padding:7px 14px;cursor:pointer'>Aceitar</button></div>";
    d.addEventListener("click", function (ev) {
      var c = ev.target.getAttribute && ev.target.getAttribute("data-c");
      if (!c) return;
      gravar(c); d.remove(); if (c === "sim") liberar();
    });
    document.body.appendChild(d);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", aviso); else aviso();
})();
