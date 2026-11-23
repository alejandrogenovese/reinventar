"""La página pública de solo lectura del resumen de una grabación (/c/<token>): HTML simple, legible en el celular y
para imprimir. Todo lo que viene de la grabación pasa por html.escape: el resumen lo escribe un LLM sobre el audio de
una charla de terceros, así que se trata como texto no confiable. Solo muestra lo de pipeline.resumen_publico."""
from html import escape

from fastapi.responses import HTMLResponse

from . import cabeceras

ESTILO = """
:root{color-scheme:light dark;--fg:#16181d;--muted:#5b6270;--bg:#fff;--line:#e3e6eb;--accent:#c2410c}
@media (prefers-color-scheme:dark){:root{--fg:#eceef2;--muted:#a3aab6;--bg:#121418;--line:#2a2e36;--accent:#fb923c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:42rem;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.5rem;line-height:1.25;margin:.25rem 0 .5rem}
h2{font-size:1.05rem;margin:1.75rem 0 .5rem;padding-top:1rem;border-top:1px solid var(--line)}
.meta,.orador,footer{color:var(--muted);font-size:.9rem;margin:0}
.meta{font-family:ui-monospace,Menlo,monospace;letter-spacing:.02em}
ul{padding-left:1.2rem;margin:0}li{margin:.35rem 0}
.servicios{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0}
.servicios li{margin:0;padding:2px 10px;border:1px solid var(--line);border-radius:999px;font-size:.9rem}
blockquote{margin:.5rem 0;padding-left:.75rem;border-left:3px solid var(--accent)}
.tiempo{color:var(--muted);font-family:ui-monospace,Menlo,monospace;font-size:.85rem}
footer{margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--line)}
button{margin-top:1.5rem;font:inherit;padding:10px 16px;border-radius:10px;border:1px solid var(--line);
  background:transparent;color:var(--fg);min-height:44px}
@media print{button{display:none}body{background:#fff;color:#000}}
"""
TITULO_APP = "ReinventAR"
NO_ENCONTRADO = "Este link no existe o ya venció."
CACHE_SEGUNDOS = 300  # corto: si se borra la grabación, el link deja de mostrarla enseguida


def _cabeceras() -> dict[str, str]:
    return {
        "Content-Security-Policy": cabeceras.politica_pagina_publica(ESTILO),
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "Cache-Control": f"private, max-age={CACHE_SEGUNDOS}",
    }


def _documento(titulo: str, cuerpo: str) -> str:
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex, nofollow\"><meta name=\"referrer\" content=\"no-referrer\">"
            f"<title>{escape(titulo)}</title><style>{ESTILO}</style></head><body><main>{cuerpo}</main></body></html>")


def _seccion(titulo: str, contenido: str) -> str:
    return f"<section><h2>{escape(titulo)}</h2>{contenido}</section>" if contenido else ""


def _lista(items: list[str], clase: str = "") -> str:
    if not items:
        return ""
    atributo = f' class="{clase}"' if clase else ""
    return f"<ul{atributo}>" + "".join(f"<li>{escape(x)}</li>" for x in items) + "</ul>"


def _cuerpo(p: dict) -> str:
    meta = " · ".join(x for x in (p["kind"], p["code"]) if x)
    anuncios = [f"<li><strong>{escape(a['service'])}</strong> — {escape(a['text'])}</li>" for a in p["announcements"]]
    citas = "".join(f"<blockquote>“{escape(q['text'])}”"
                    + (f" <span class=\"tiempo\">{escape(q['time'])}</span>" if q["time"] else "") + "</blockquote>"
                    for q in p["quotes"] if q["text"])
    return "".join([
        f"<p class=\"meta\">{escape(meta)}</p>" if meta else "",
        f"<h1>{escape(p['title'])}</h1>",
        f"<p class=\"orador\">{escape(p['speaker'])}</p>" if p["speaker"] else "",
        _seccion("En corto", f"<p>{escape(p['tldr'])}</p>" if p["tldr"] else ""),
        _seccion("Anuncios", "<ul>" + "".join(anuncios) + "</ul>" if anuncios else ""),
        _seccion("Puntos clave", _lista(p["key_points"])),
        _seccion("Servicios mencionados", _lista(p["services"], "servicios")),
        _seccion("Frases", citas),
        # El botón arranca oculto: lo muestra /js/imprimir.js (sin script inline, por la CSP). Sin JS, no aparece.
        "<button type=\"button\" id=\"imprimir\" hidden>Imprimir o guardar en PDF</button>",
        "<footer>Resumen hecho con IA a partir de la grabación de la charla. Compartido desde ReinventAR.</footer>",
        "<script src=\"/js/imprimir.js\" defer></script>",
    ])


def pagina(p: dict) -> HTMLResponse:
    """La página del resumen; `p` es lo que devuelve pipeline.resumen_publico."""
    return HTMLResponse(_documento(f"{p['title']} · {TITULO_APP}", _cuerpo(p)), headers=_cabeceras())


def no_encontrado(status: int = 404, texto: str = NO_ENCONTRADO) -> HTMLResponse:
    """Para cualquier falla (link adulterado, vencido, de otra cosa, grabación borrada o sin resumen): la misma
    respuesta, para no dar pistas de qué existe."""
    return HTMLResponse(_documento(TITULO_APP, f"<h1>{escape(texto)}</h1>"), status_code=status, headers=_cabeceras())
