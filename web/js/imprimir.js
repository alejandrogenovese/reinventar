// Botón «Imprimir o guardar en PDF» de la página pública del resumen (/c/<token>, app/grabaciones_pagina.py).
// Va en un archivo aparte porque esa página no admite scripts inline (CSP).
const boton = document.getElementById("imprimir");
if (boton) {
  boton.hidden = false;
  boton.addEventListener("click", () => window.print());
}
