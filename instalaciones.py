"""Primer registro de datos de cada estación: aproxima su fecha de instalación.

La API no informa cuándo se instaló una estación. Lo más cercano es el registro más
antiguo de su historial (`/{tipo}/{codigo}`). Ese dato no cambia nunca, así que se
guarda en `data/primer_registro.json` y solo se consultan las estaciones que aún no
estén en el archivo. Consultarlo es caro (decenas de segundos en estaciones con
millones de filas), por eso la carga inicial se hace una vez con:

    python instalaciones.py
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from pathlib import Path

import pandas as pd

import sama_api  # primero: inyecta truststore antes de que se importe requests
import requests  # noqa: E402

REGISTRO = Path(__file__).parent / "data" / "primer_registro.json"
RUTA_HISTORIAL = {categoria: ruta for categoria, (ruta, _) in sama_api.RUTAS.items()}

# Dentro de la app solo se completan unas pocas estaciones nuevas, con plazo corto.
MAX_NUEVAS = 8
HILOS_APP = 4
PLAZO_APP_SEG = 25
HILOS_CARGA = 6

_sesion = requests.Session()


def _historial(categoria: str, codigo: str, **params) -> dict:
    resp = _sesion.get(
        f"{sama_api.BASE_URL}/{RUTA_HISTORIAL[categoria]}/{codigo}",
        params=params, timeout=(10, 120),
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.json()


def _total(respuesta: dict) -> int | None:
    # niveles, pluviómetros y meteorología traen `count`; alarmas, `total`.
    return respuesta.get("count", respuesta.get("total"))


def primer_registro(categoria: str, codigo: str) -> str | None:
    """`created_at` (ISO, UTC) del registro más antiguo de la estación, o None si aún no
    tiene registros. El historial va de más reciente a más antiguo: se pide el total y
    luego la última página de tamaño 1. Lanza excepción si la API falla o cambia de formato."""
    total = _total(_historial(categoria, codigo, size=1))
    if total is None:
        raise KeyError("la respuesta no trae `count` ni `total`")
    if total == 0:
        return None
    for _ in range(3):  # si llegaron registros entre las dos consultas, la última página se corre
        ultima = _historial(categoria, codigo, size=1, page=total)
        nuevo_total = _total(ultima)
        if nuevo_total in (None, total):
            break
        total = nuevo_total
    filas = ultima.get("values", ultima.get("results"))
    if not filas:
        raise ValueError("la última página vino vacía")
    return filas[0]["created_at"]


def cargar_registro() -> dict:
    """{codigo: {"tipo": ..., "primer_registro": iso | None}}; vacío si no hay archivo."""
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8")).get("estaciones", {})
    except (OSError, ValueError):
        return {}


def guardar_registro(estaciones: dict) -> None:
    REGISTRO.parent.mkdir(exist_ok=True)
    temporal = REGISTRO.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(
            {"actualizado": datetime.now(sama_api.BOGOTA).isoformat(), "estaciones": estaciones},
            ensure_ascii=False, sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.replace(temporal, REGISTRO)  # reemplazo atómico: nunca queda un archivo a medias


def _pendientes(df: pd.DataFrame, registro: dict) -> list[tuple[str, str]]:
    """Estaciones sin primer registro conocido (nuevas, o que aún no tenían datos)."""
    return [
        (categoria, codigo) for categoria, codigo in zip(df["categoria"], df["codigo"])
        if registro.get(codigo, {}).get("primer_registro") is None
    ]


def aplicar(df: pd.DataFrame, completar: bool) -> None:
    """Agrega a `df` la columna `primer_registro` (hora de Colombia; NaT si no se conoce).

    Con `completar` consulta a la API unas pocas estaciones pendientes; si falla alguna
    se omite y el tablero sigue funcionando."""
    registro = cargar_registro()
    if completar:
        try:
            nuevos = _completar_en_la_app(_pendientes(df, registro)[:MAX_NUEVAS])
            if nuevos:
                registro.update(nuevos)
                guardar_registro(registro)
        except Exception:
            pass  # el indicador es opcional: sin red o sin permiso de escritura, se usa lo guardado
    fechas = df["codigo"].map(lambda c: registro.get(c, {}).get("primer_registro"))
    df["primer_registro"] = pd.to_datetime(
        fechas, utc=True, format="ISO8601", errors="coerce"
    ).dt.tz_convert(sama_api.BOGOTA)


def _completar_en_la_app(pendientes: list[tuple[str, str]]) -> dict:
    if not pendientes:
        return {}
    pool = ThreadPoolExecutor(HILOS_APP)
    futuros = {pool.submit(primer_registro, cat, cod): (cat, cod) for cat, cod in pendientes}
    hechos, _ = wait(futuros, timeout=PLAZO_APP_SEG)
    pool.shutdown(wait=False, cancel_futures=True)
    nuevos = {}
    for futuro in hechos:
        categoria, codigo = futuros[futuro]
        if futuro.exception() is None:
            nuevos[codigo] = {"tipo": categoria, "primer_registro": futuro.result()}
    return nuevos


def cargar_todo() -> None:
    """Carga inicial: consulta el primer registro de todas las estaciones pendientes."""
    df = sama_api.construir(sama_api.descargar_crudo()).estaciones
    registro = cargar_registro()
    pendientes = _pendientes(df, registro)
    print(f"{len(df)} estaciones; {len(pendientes)} por consultar ({HILOS_CARGA} a la vez).")
    inicio, fallos = time.time(), []
    with ThreadPoolExecutor(HILOS_CARGA) as pool:
        futuros = {pool.submit(primer_registro, cat, cod): (cat, cod) for cat, cod in pendientes}
        for i, futuro in enumerate(as_completed(futuros), 1):
            categoria, codigo = futuros[futuro]
            try:
                registro[codigo] = {"tipo": categoria, "primer_registro": futuro.result()}
                estado = (registro[codigo]["primer_registro"] or "sin registros")[:10]
            except Exception as exc:
                fallos.append(codigo)
                estado = f"FALLÓ ({type(exc).__name__}: {str(exc)[:60]})"
            print(f"[{i}/{len(pendientes)}] {codigo:8} {estado}  ({time.time() - inicio:.0f} s)", flush=True)
            if i % 20 == 0:
                guardar_registro(registro)  # punto de control: si se corta, se retoma donde quedó
    guardar_registro(registro)
    print(f"\nListo en {time.time() - inicio:.0f} s. Guardado en {REGISTRO}. Fallos: {fallos or 'ninguno'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cargar_todo()
