"""Notificaciones en el celular con la app cerrada (Web Push), sin dependencias nuevas: solo `cryptography`.

- Cifrado del mensaje: RFC 8291 (aes128gcm, RFC 8188). Firma del servidor: VAPID (RFC 8292, JWT ES256).
- Claves: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY (base64url, generar con `python -m app.push`) y VAPID_SUBJECT.
- Cada minuto, para quienes activaron las notificaciones: "Salí para…" (20 min antes de lo fijado, o de la hora de la
  cola si la charla no está reservada: el servidor no conoce la ubicación), "Empieza en 5 min", "Salí a las HH:MM para
  llegar a…" (si eligió irse antes en el armado guiado), los cambios del itinerario (app/changes.py) y el recordatorio
  "¿la grabás?" (app/recordatorio.py). Cada aviso sale una sola vez. En modo prueba usa el reloj y la sede simulados.
En iPhone funciona solo con la app instalada en la pantalla de inicio (iOS 16.4 o posterior).
"""
import base64
import datetime as dt
import hashlib
import json
import logging
import os
import struct
import threading
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import changes, config, db, eventos_avisos, itinerary, leave, lleno, recordatorio, sandbox, travel, venues

log = logging.getLogger("reinventar.push")
TICK_SECONDS = 60
LEAVE_LEAD_MIN = 20
START_NOTICE_MIN = 5
RECORD_SIZE = 4096
TTL_SECONDS = 3600


# ---------- base64url y claves ----------

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid_keys() -> tuple[str, str]:
    """(pública, privada) en base64url: la pública va al navegador (applicationServerKey)."""
    private = ec.generate_private_key(ec.SECP256R1())
    return b64u(_raw_public(private.public_key())), b64u(private.private_numbers().private_value.to_bytes(32, "big"))


def _vapid_private() -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(unb64u(config.VAPID_PRIVATE_KEY), "big"), ec.SECP256R1())


def enabled() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


# ---------- RFC 8291 + VAPID ----------

def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Cuerpo cifrado para el push service (Content-Encoding: aes128gcm). salt y server_key solo para tests."""
    ua_public = unb64u(p256dh)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(server_key.public_key())
    ecdh = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hkdf(unb64u(auth), ecdh, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 = último (y único) registro
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


def vapid_authorization(endpoint: str, now: float | None = None) -> str:
    parts = urlsplit(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
                              "sub": config.VAPID_SUBJECT}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(_vapid_private().sign(signing_input, ec.ECDSA(hashes.SHA256())))
    jwt = f"{header}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={config.VAPID_PUBLIC_KEY}"


def send(sub: dict, message: dict, http: httpx.Client | None = None, ttl: int = TTL_SECONDS) -> int:
    """Manda un aviso a una suscripción. Devuelve el status; 404/410 = suscripción vencida (se borra).
    ttl: cuánto lo guarda el servicio de push si el celular está apagado o sin señal."""
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    headers = {"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(ttl),
               "Urgency": "high", "Authorization": vapid_authorization(sub["endpoint"])}
    r = (http or httpx).post(sub["endpoint"], content=body, headers=headers, timeout=15)
    if r.status_code in (404, 410):
        db.delete_push_subscription(sub["endpoint"])
    elif r.status_code >= 400:
        log.warning("push %s respondió %s: %s", urlsplit(sub["endpoint"]).netloc, r.status_code, r.text[:200])
    return r.status_code


def notify(username: str, message: dict) -> int:
    """Manda el aviso a todos los dispositivos del usuario; devuelve a cuántos llegó.
    Si el mensaje trae "ttl", se usa como TTL del push y no viaja al celular."""
    ttl = message.get("ttl", TTL_SECONDS)
    payload = {k: v for k, v in message.items() if k != "ttl"}
    return sum(send(sub, payload, ttl=ttl) < 300 for sub in db.push_subscriptions(username))


# ---------- qué avisar ----------

def _at(day: str, hhmm_: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm_}").replace(tzinfo=sandbox.EVENT_TZ)


def _url(c: dict) -> str:
    return {"event": f"/#/evento/{c['code']}", "mine": "/#/itinerario"}.get(c.get("kind"), f"/#/charla/{c['base']}")


def _notice(c: dict, now: dt.datetime, grabar: bool = False) -> tuple[str, dict] | None:
    """Aviso de "salí" (contra la hora de la cola si no está reservada) o "empieza" para algo fijado, si corresponde.
    grabar: el "empieza" de una charla suma "¿La grabás?" y abre su grabación (regla A de app/recordatorio.py)."""
    if not (c.get("locked") and c.get("start")):
        return None
    venue = c.get("venue") or {}
    where = " · ".join(filter(None, (venue.get("hotel"), venue.get("detail"))))
    to_arrive = (_at(c["day"], leave.arrive_by(c)) - now).total_seconds() / 60
    if START_NOTICE_MIN < to_arrive <= LEAVE_LEAD_MIN:
        cuando = (f"Sin reserva: hacé la cola desde las {leave.arrive_by(c)}" if leave.needs_queue(c)
                  else f"Empieza a las {c['start']}")
        return (f"leave:{c['code']}:{c['day']}",
                {"title": f"Salí para {c['title']}", "body": f"{cuando} · {where}", "url": _url(c)})
    to_start = (_at(c["day"], c["start"]) - now).total_seconds() / 60
    if 0 < to_start <= START_NOTICE_MIN:
        key = f"start:{c['code']}:{c['day']}"
        msg = {"title": f"{c['title']} empieza en {round(to_start)} min", "body": where, "url": _url(c)}
        if grabar and c.get("kind", "talk") == "talk":
            msg = recordatorio.con_grabar(key, c["code"],
                                          {**msg, "body": " · ".join(filter(None, (where, "¿La grabás?")))})
        return key, msg
    return None


def _early_notice(c: dict, siguiente: dict | None, now: dt.datetime) -> tuple[str, dict] | None:
    """ "Salí a las HH:MM para llegar a X": para la charla de la que eligió irse antes (armado guiado)."""
    sale = leave.leave_early_at(c)
    if not sale or not siguiente:
        return None
    falta = (_at(c["day"], sale) - now).total_seconds() / 60
    if not 0 < falta <= START_NOTICE_MIN:
        return None
    destino = (siguiente.get("venue") or {}).get("hotel") or ""
    return (f"early:{c['code']}:{c['day']}",
            {"title": f"Salí a las {sale} para llegar a {siguiente['title']}",
             "body": " · ".join(filter(None, (destino, f"empieza a las {siguiente['start']}"))), "url": _url(siguiente)})


def day_notices(cards: list[dict], now: dt.datetime, grabar: bool = False) -> list[tuple[str, dict]]:
    """Avisos de un día del itinerario (cards en orden de inicio)."""
    con_hora = [c for c in cards if c.get("start")]
    out = [n for c in con_hora if (n := _notice(c, now, grabar))]
    for i, c in enumerate(con_hora):
        n = _early_notice(c, con_hora[i + 1] if i + 1 < len(con_hora) else None, now)
        if n:
            out.append(n)
    return out


def _alguien_graba(username: str, code: str) -> bool:
    """Si ya hay una grabación de esa charla (las grabaciones son compartidas: alcanza con que la grabe alguien)."""
    # cuando exista sessions.created_by: filtrar por usuario
    ahora = time.time()
    return db.grabacion_activa(code, ahora - recordatorio.GRABACION_RECIENTE_MIN * 60,
                               ahora - recordatorio.CHUNK_ACTIVO_MIN * 60)


def _sede_reciente(username: str, prefs: recordatorio.Preferencias) -> recordatorio.Sede | None:
    """La sede donde está, si la consulta de ubicación está prendida y el dato es reciente. En modo prueba manda la
    sede simulada."""
    sb = sandbox.actual()
    if sb and sb.id_sede is not None:
        id_sede = sb.id_sede
    elif prefs.ubicacion:
        fila = db.get_ubicacion(username, time.time() - recordatorio.UBICACION_VIGENCIA_MIN * 60)
        id_sede = fila["id_sede"] if fila else None
    else:
        id_sede = None
    sede = venues.by_id(id_sede)
    return recordatorio.Sede(sede["id"], sede["name"]) if sede else None


def _viaje_min(origen: int, destino: int) -> int | None:
    v = travel.viaje(origen, destino)
    return v.minutos if v else None


def _recordatorios(username: str, days: list[dict], now: dt.datetime,
                   prefs: recordatorio.Preferencias) -> list[tuple[str, dict]]:
    hoy = now.strftime("%Y-%m-%d")
    cards = [{**c, "id_sede": venues.id_by_name((c.get("venue") or {}).get("hotel"))}
             for d in days if d["day"] == hoy for c in d["sessions"]]
    if not cards:
        return []
    ultimo = db.ultimo_push(username, recordatorio.PREFIJO)
    return recordatorio.recordatorios(
        cards, now, sede=_sede_reciente(username, prefs), prefs=prefs,
        grabando=lambda code: _alguien_graba(username, code), viaje_min=_viaje_min,
        minutos_desde_ultimo=(time.time() - ultimo) / 60 if ultimo else None)


def due(username: str, now: dt.datetime) -> list[tuple[str, dict]]:
    """[(clave única, mensaje)] de lo que corresponde avisar ahora a este usuario."""
    prefs = recordatorio.Preferencias(**db.get_preferencias_avisos(username))
    days = itinerary.get_current(username)["days"]
    out = [n for day in days for n in day_notices(day["sessions"], now, prefs.grabar)]
    out += _recordatorios(username, days, now, prefs)
    out += eventos_avisos.avisos(days, now, quiere_nuevos=prefs.eventos_nuevos,
                                 ultimo_nuevos=db.ultimo_push(username, eventos_avisos.PREFIJO_NUEVOS))
    if recordatorio.en_silencio(now):  # los cambios siguen pendientes: el aviso sale a la mañana
        return out
    for ch in changes.pending(username):
        key = "change:" + hashlib.sha256(json.dumps([ch["code"], ch["messages"]]).encode()).hexdigest()[:16]
        title = ch.get("push_title") or "Cambió algo de tu itinerario"
        out.append((key, {"title": title, "body": " ".join(ch["messages"]), "url": "/#/itinerario"}))
    return out


def tick() -> int:
    """Una vuelta: avisa lo que corresponde a cada usuario suscripto. Devuelve cuántos avisos salieron."""
    sent = 0
    db.purgar_ubicaciones(time.time() - recordatorio.UBICACION_BORRADO_MIN * 60)
    db.purgar_reportes_lleno(time.time() - lleno.BORRADO_H * 3600)
    with sandbox.real():
        users = db.push_usernames()
    for username in users:
        with sandbox.real():
            sb = sandbox.desde_usuario(db.get_user(username))
        with sandbox.activar(sb):  # en modo prueba: su reloj simulado y su schema de prueba
            for key, message in due(username, sandbox.ahora()):
                if not db.mark_push_sent(username, key):
                    continue  # ya avisado
                if notify(username, message):
                    sent += 1
                else:
                    db.unmark_push_sent(username, key)  # no llegó a ningún dispositivo: se reintenta la próxima vuelta
    return sent


def _loop():
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001 — un error de una vuelta no corta las siguientes
            log.exception("vuelta de avisos falló")
        time.sleep(TICK_SECONDS)


def start_worker() -> None:
    if enabled():
        threading.Thread(target=_loop, name="push", daemon=True).start()
    else:
        log.info("Web Push deshabilitado: faltan VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY")


if __name__ == "__main__":
    pub, priv = generate_vapid_keys()
    print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}\nVAPID_SUBJECT=mailto:<tu mail>")
