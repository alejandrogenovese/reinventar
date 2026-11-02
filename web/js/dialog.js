// Diálogos propios (reemplazan confirm/prompt del navegador): <dialog> nativo, foco atrapado y Esc para cancelar.
import { h } from "./ui.js";

/**
 * Abre un diálogo modal y resuelve con el valor elegido.
 * @param {{ title: string, text?: string, confirmLabel?: string, cancelLabel?: string, danger?: boolean,
 *           input?: { label: string, type?: string, minlength?: number } }} opts
 * @returns {Promise<boolean|string|null>} confirm: true/false; con input: el texto o null si se cancela.
 */
function openDialog({ title, text, confirmLabel = "Aceptar", cancelLabel = "Cancelar", danger = false, input }) {
  return new Promise((resolve) => {
    const field = input ? h("input", { id: "dlg-input", type: input.type || "text", minlength: input.minlength, required: true, autocomplete: "off" }) : null;
    const form = h("form", { method: "dialog", class: "ra-dialog-body" },
      h("h2", { class: "ra-dialog-title", id: "dlg-title" }, title),
      text ? h("p", { class: "ra-dialog-text" }, text) : null,
      field ? h("div", { class: "field" }, h("label", { class: "label", for: "dlg-input" }, input.label), field) : null,
      h("div", { class: "actions" },
        h("button", { type: "button", class: "ra-btn ra-btn-secondary", value: "cancel", onclick: () => dlg.close("cancel") }, cancelLabel),
        h("button", { type: "submit", class: `ra-btn ra-btn-${danger ? "danger" : "primary"}`, value: "ok" }, confirmLabel)));
    const dlg = h("dialog", { class: "ra-dialog", "aria-labelledby": "dlg-title" }, form);

    dlg.addEventListener("close", () => {
      const ok = dlg.returnValue === "ok";
      dlg.remove();
      resolve(input ? (ok ? field.value : null) : ok);
    });
    document.body.append(dlg);
    dlg.showModal();
    (field || form.querySelector("[value=cancel]")).focus(); // en lo destructivo, el foco arranca en Cancelar
  });
}

export const confirmDialog = (title, opts = {}) => openDialog({ title, ...opts });
export const promptDialog = (title, input, opts = {}) => openDialog({ title, input, ...opts });
