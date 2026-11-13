/* Cofre Aberto MS — configuração do botão "Apoie" (Pix).
   Preencha a chave Pix, o nome do recebedor e a cidade. Com a chave vazia, o botão "Apoie" fica escondido
   em todas as páginas e a página /apoie/ mostra "em breve". */
window.APOIE = {
  chave: "6d93e3cc-c108-42d7-bf5e-e73a5731685a",               // chave Pix: CPF, CNPJ, e-mail, telefone (+5567...) ou chave aleatória
  nome: "Fabricio Batista",                // nome do recebedor como aparece no banco (até 25 letras)
  cidade: "CAMPO GRANDE",  // cidade do recebedor (até 15 letras)
};
(function () {
  if (!window.APOIE.chave) return;
  var mostrar = function () { document.querySelectorAll(".btn-apoie").forEach(function (b) { b.style.display = b.dataset.d || (b.tagName === "A" && b.closest(".sidebar") ? "flex" : ""); }); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mostrar); else mostrar();
})();
