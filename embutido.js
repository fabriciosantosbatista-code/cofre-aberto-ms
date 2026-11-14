/* Cofre Aberto MS — quando uma página (boletim, empresas, órgãos, municípios, metodologia) é aberta DENTRO do painel
   (num quadro), esconde o cabeçalho, o rodapé e o mapa do site dela — o painel já tem o menu — e faz os links que
   levam ao painel ou à capa abrirem na janela inteira. */
(function () {
  if (window.top === window.self) return;
  document.documentElement.classList.add("embutido");
  var st = document.createElement("style");
  st.textContent = ".embutido .page>nav,.embutido body>nav,.embutido footer,.embutido .mapa-site{display:none!important}" +
    ".embutido .page{padding-top:4px}";
  document.head.appendChild(st);
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("a[href]");
    if (!a) return;
    var u = new URL(a.href, location.href);
    if (u.origin !== location.origin || /cofre-aberto-ms\.html$/.test(u.pathname) || u.pathname === "/" || u.pathname === "/index.html") a.target = "_top";
  }, true);
})();
