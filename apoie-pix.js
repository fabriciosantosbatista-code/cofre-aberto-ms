/* Cofre Aberto MS — gera o Pix (BR Code estático do Banco Central) com o valor escolhido e desenha o QR Code. */
(function () {
  var cfg = window.APOIE || {};
  var caixa = document.getElementById("pix");
  if (!caixa) return;
  if (!cfg.chave) { caixa.innerHTML = "<p class='aviso'>As doações por Pix abrem em breve.</p>"; return; }
  var limpa = function (t, n) { return (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9 .\-@+]/g, "").toUpperCase().slice(0, n); };
  var campo = function (id, v) { return id + String(v.length).padStart(2, "0") + v; };
  var crc16 = function (s) {
    var c = 0xFFFF;
    for (var i = 0; i < s.length; i++) { c ^= s.charCodeAt(i) << 8; for (var j = 0; j < 8; j++) c = c & 0x8000 ? (c << 1) ^ 0x1021 : c << 1; c &= 0xFFFF; }
    return c.toString(16).toUpperCase().padStart(4, "0");
  };
  var brcode = function (valor) {
    var p = campo("00", "01") + campo("26", campo("00", "br.gov.bcb.pix") + campo("01", cfg.chave.trim())) + campo("52", "0000") + campo("53", "986") +
      (valor ? campo("54", valor.toFixed(2)) : "") + campo("58", "BR") + campo("59", limpa(cfg.nome, 25) || "COFRE ABERTO MS") +
      campo("60", limpa(cfg.cidade, 15) || "CAMPO GRANDE") + campo("62", campo("05", "COFREABERTO")) + "6304";
    return p + crc16(p);
  };
  caixa.innerHTML =
    "<div class='pix-valores'>" + [10, 25, 50, 100].map(function (v) { return "<button data-v='" + v + "'>R$ " + v + "</button>"; }).join("") +
    "<button data-v='0'>Outro valor</button></div>" +
    "<div class='pix-corpo'><div id='pix-qr'></div><div class='pix-txt'><p id='pix-rot'></p>" +
    "<textarea id='pix-codigo' readonly rows='4'></textarea><button id='pix-copiar' class='btn-painel'>Copiar código Pix</button>" +
    "<p class='aviso' style='margin-top:10px'>Abra o app do seu banco, escolha Pix → Ler QR Code ou Pix Copia e Cola. Recebedor: <b>" +
    limpa(cfg.nome, 25).replace(/</g, "") + "</b>.</p></div></div>";
  var escolher = function (v, botao) {
    caixa.querySelectorAll(".pix-valores button").forEach(function (b) { b.classList.toggle("ativo", b === botao); });
    var cod = brcode(v);
    document.getElementById("pix-codigo").value = cod;
    document.getElementById("pix-rot").textContent = v ? "Pix de R$ " + v.toFixed(2).replace(".", ",") : "Pix de valor livre (você digita o valor no app do banco)";
    var alvo = document.getElementById("pix-qr");
    alvo.innerHTML = "";
    if (window.qrcode) { var q = qrcode(0, "M"); q.addData(cod); q.make(); alvo.innerHTML = q.createSvgTag(4, 2); }
    else alvo.style.display = "none";
  };
  caixa.querySelectorAll(".pix-valores button").forEach(function (b) {
    b.addEventListener("click", function () { escolher(+b.dataset.v, b); });
  });
  document.getElementById("pix-copiar").addEventListener("click", function () {
    var t = document.getElementById("pix-codigo"); t.select();
    (navigator.clipboard ? navigator.clipboard.writeText(t.value) : Promise.reject()).catch(function () { document.execCommand("copy"); });
    this.textContent = "Código copiado ✓"; var b = this; setTimeout(function () { b.textContent = "Copiar código Pix"; }, 2500);
  });
  escolher(25, caixa.querySelector("[data-v='25']"));
})();
