"""Cliente mínimo de la People Search API de Crustdata (POST /person/search, versión 2025-11-01).

- Respeta el límite de 30 consultas por minuto y reintenta los 429 y los 5xx con espera.
- Guarda cada respuesta en un caché local (fuera del repo: son datos personales) para no pagar dos veces la misma
  consulta, por ejemplo entre el modo prueba y --aplicar.
"""
import hashlib
import json
import time
from pathlib import Path

import httpx

URL = "https://api.crustdata.com/person/search"
API_VERSION = "2025-11-01"
SEGUNDOS_ENTRE_CONSULTAS = 2.1  # 30 por minuto, con margen
REINTENTOS = 4
ESPERA_REINTENTO = 20  # segundos; se duplica en cada reintento

# Lo que se pide de cada perfil (cada grupo premium suma créditos: experiencia y educación, 0,1 cada uno).
CAMPOS = [
    "basic_profile.name", "basic_profile.headline", "basic_profile.location",
    "social_handles.professional_network_identifier.profile_url", "social_handles.twitter_identifier.slug",
    "social_handles.dev_platform_identifier.profile_url",
    "experience.employment_details.current", "experience.employment_details.past", "education.schools",
]


class CrustdataError(Exception):
    """La API respondió con un error que no se arregla reintentando (credenciales, request inválido)."""


class Cliente:
    def __init__(self, api_key: str, cache_dir: Path, *, http: httpx.Client | None = None):
        if not api_key:
            raise CrustdataError("Falta CRUSTDATA_API_KEY")
        self._headers = {"Authorization": f"Bearer {api_key}", "x-api-version": API_VERSION,
                         "Content-Type": "application/json"}
        self._cache = cache_dir
        self._cache.mkdir(parents=True, exist_ok=True)
        self._http = http or httpx.Client(timeout=60)
        self._ultima = 0.0
        self.creditos = 0.0
        self.consultas = 0

    def buscar(self, filtros: dict, limite: int) -> list[dict]:
        """Perfiles que cumplen los filtros (a lo sumo `limite`). Usa el caché si la consulta ya se hizo."""
        cuerpo = {"filters": filtros, "fields": CAMPOS, "limit": limite}
        archivo = self._cache / (hashlib.sha256(json.dumps(cuerpo, sort_keys=True).encode()).hexdigest() + ".json")
        if archivo.exists():
            return json.loads(archivo.read_text(encoding="utf-8")).get("profiles") or []
        respuesta = self._post(cuerpo)
        archivo.write_text(json.dumps(respuesta, ensure_ascii=False), encoding="utf-8")
        return respuesta.get("profiles") or []

    def _post(self, cuerpo: dict) -> dict:
        espera = ESPERA_REINTENTO
        estado = None
        for intento in range(REINTENTOS + 1):
            time.sleep(max(0.0, self._ultima + SEGUNDOS_ENTRE_CONSULTAS - time.monotonic()))
            self._ultima = time.monotonic()
            r = self._http.post(URL, headers=self._headers, json=cuerpo)
            estado = r.status_code
            if estado == 429 or estado >= 500:
                if intento < REINTENTOS:
                    time.sleep(espera)
                    espera *= 2
                continue
            if estado >= 400:
                raise CrustdataError(f"Crustdata {estado}: {r.text[:300]}")
            self.consultas += 1
            self.creditos += float(r.headers.get("X-Credits-Used") or 0)
            return r.json()
        raise CrustdataError(f"Crustdata siguió respondiendo {estado} después de {REINTENTOS} reintentos")
