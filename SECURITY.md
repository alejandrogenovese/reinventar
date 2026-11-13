# Seguridad

## Versiones soportadas

ReinventAR se despliega de forma continua: producción es siempre el último commit de `main` (la versión de
`app/__init__.py`, ver [CHANGELOG.md](CHANGELOG.md)). Solo esa versión recibe arreglos de seguridad; no hay ramas de
mantenimiento para versiones anteriores.

| Versión | Soportada |
|---|---|
| La última publicada (rama `main`) | Sí |
| Anteriores | No |

## Cómo reportar una vulnerabilidad

**No abras un issue público.** Reportala en privado con GitHub Security Advisories:

1. Entrá a [Reportar una vulnerabilidad](https://github.com/alejandrogenovese/reinventar/security/advisories/new)
   (pestaña *Security* del repo → *Report a vulnerability*).
2. Contá qué encontraste, cómo reproducirlo, qué impacto tiene y, si podés, una idea de arreglo.

Qué esperar:

- Una primera respuesta dentro de los 7 días.
- Si se confirma, el arreglo va a `dev` y llega a producción con la promoción automática a `main`; el aviso se publica
  después del arreglo, con crédito a quien lo reportó si así lo quiere.

## Alcance

Entra la app (backend FastAPI en `app/`, PWA en `web/`), los workflows de `.github/` y la configuración del gateway en
`infra/`. No entran los servicios de terceros que usa (Railway, Anthropic, Groq, Langfuse, Google Maps): reportá esos
problemas a cada proveedor.

Si encontrás un secreto expuesto en el repo o en su historial, reportalo por el mismo canal privado.
