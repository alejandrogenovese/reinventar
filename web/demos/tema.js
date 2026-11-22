// El mismo tema que la app (web/index.html): lo elegido en Ajustes o, si no hay nada, el del sistema. Va como archivo
// aparte y sin defer, antes del CSS, para que no se vea un parpadeo claro (la CSP no deja scripts inline acá).
(function () {
  let elegido = null;
  try { elegido = localStorage.getItem("reinventar.theme"); } catch { /* sin localStorage: se usa el del sistema */ }
  const sistema = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = elegido === "light" || elegido === "dark" ? elegido : sistema;
})();
