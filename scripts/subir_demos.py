"""Sube los videos demo compuestos (demos/out/final/<feature>.mp4) al bucket de demos, a través de la app.

La app de staging tiene las credenciales del bucket (variables DEMOS_S3_*): el script entra con un usuario admin y usa
PUT /api/admin/demos/archivos/<nombre> e /api/admin/demos/indice. Por cada video saca una portada (el cuadro de la placa
de título) con ffmpeg. El orden de la galería es el de demos/features.yml; las de admin no se publican.

Uso:
  DEMOS_ADMIN_PASSWORD=... python scripts/subir_demos.py [--base-url https://staging.reinventar.app] [--usuario tester]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import yaml

RAIZ = Path(__file__).resolve().parent.parent
PORTADA_SEGUNDO = "1.5"  # mitad de la placa de título: ya terminó el fundido de entrada
TIMEOUT_SUBIDA_S = 120


def orden_de_features(features_yml: Path) -> list[str]:
    """Ids de demos/features.yml en orden, sin las de audiencia admin."""
    features = yaml.safe_load(features_yml.read_text(encoding="utf-8"))["features"]
    return [f["id"] for f in features if f.get("audiencia") != "admin"]


def armar_indice(orden: list[str], libretos: dict[str, dict], duraciones: dict[str, int]) -> list[dict]:
    """Una entrada por video que exista, en el orden de features.yml; las que no tienen video se saltean."""
    return [{"feature": f, "titulo": libretos[f]["titulo"], "beneficio": libretos[f].get("beneficio", ""),
             "duracion_s": duraciones[f], "video": f"{f}.mp4", "poster": f"{f}.jpg"}
            for f in orden if f in duraciones and f in libretos]


def leer_libretos(carpeta: Path) -> dict[str, dict]:
    return {d["feature"]: d for d in (yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(carpeta.glob("*.yml")))}


def duracion_s(video: Path) -> int:
    salida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                            check=True, capture_output=True, text=True).stdout
    return round(float(salida))


def portada(video: Path, destino: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", PORTADA_SEGUNDO, "-i", str(video), "-frames:v", "1",
                    "-vf", "scale=960:-2", "-q:v", "4", str(destino)], check=True)


def login(cliente: httpx.Client, usuario: str, password: str) -> None:
    r = cliente.post("/api/login", json={"username": usuario, "password": password})
    if r.status_code != 200:
        sys.exit(f"No se pudo entrar como {usuario}: HTTP {r.status_code}")
    cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"


def subir(cliente: httpx.Client, nombre: str, datos: bytes) -> None:
    r = cliente.put(f"/api/admin/demos/archivos/{nombre}", content=datos, timeout=TIMEOUT_SUBIDA_S)
    if r.status_code != 200:
        sys.exit(f"No se pudo subir {nombre}: HTTP {r.status_code} {r.text}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base-url", default="https://staging.reinventar.app")
    p.add_argument("--usuario", default=os.environ.get("DEMOS_ADMIN_USUARIO", "tester"))
    p.add_argument("--videos", type=Path, default=RAIZ / "demos" / "out" / "final")
    args = p.parse_args()
    password = os.environ.get("DEMOS_ADMIN_PASSWORD")
    if not password:
        sys.exit("Falta DEMOS_ADMIN_PASSWORD (la contraseña del usuario admin)")
    videos = {v.stem: v for v in sorted(args.videos.glob("*.mp4"))}
    if not videos:
        sys.exit(f"No hay videos en {args.videos}")

    with httpx.Client(base_url=args.base_url, timeout=30) as cliente, tempfile.TemporaryDirectory() as tmp:
        login(cliente, args.usuario, password)
        duraciones = {}
        for feature, video in videos.items():
            jpg = Path(tmp) / f"{feature}.jpg"
            portada(video, jpg)
            subir(cliente, f"{feature}.mp4", video.read_bytes())
            subir(cliente, f"{feature}.jpg", jpg.read_bytes())
            duraciones[feature] = duracion_s(video)
            print(f"subido {feature}")
        indice = armar_indice(orden_de_features(RAIZ / "demos" / "features.yml"),
                              leer_libretos(RAIZ / "demos" / "libretos"), duraciones)
        r = cliente.put("/api/admin/demos/indice", json=indice)
        if r.status_code != 200:
            sys.exit(f"No se pudo guardar el índice: HTTP {r.status_code} {r.text}")
        print(f"índice con {len(indice)} demos")


if __name__ == "__main__":
    main()
