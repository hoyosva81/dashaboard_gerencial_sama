"""Descarga y normalización de los datos de la API de SAMA (GeoJSON)."""

import json
import os
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import truststore

# Usa el almacén de certificados del sistema. Necesario cuando un antivirus
# (p. ej. Avast) inspecciona HTTPS y re-firma con su propia CA, que Python
# no conoce. Debe ejecutarse antes de importar requests.
truststore.inject_into_ssl()

import requests  # noqa: E402

import mapa_calor  # noqa: E402
from catalogos import (  # noqa: E402
    COLUMNAS_MEDIDA, ESTACIONES_SIN_CALOR, NOMBRE_TIPO, SENTINELA, SIN_ASIGNAR,
)

BASE_URL = os.environ.get("SAMA_BASE_URL", "https://sama-dagran.duckdns.org:8443/api/v1")
TTL_SEGUNDOS = 24 * 60 * 60
SNAPSHOT = Path(__file__).parent / "data" / "snapshot.json"
BOGOTA = timezone(timedelta(hours=-5))  # Colombia no tiene horario de verano

# categoría -> (ruta, parámetros). Son los parámetros con que se consultan los
# endpoints; `offset` descarta los primeros N registros, así que 0 trae todo.
RUTAS = {
    "NIVELES": ("niveles", {}),
    "METEOROLOGIA": ("meteorologia", {"offset": 0}),
    "PLUVIOMETROS": ("pluviometros", {}),
    "ALARMAS": ("alarmas", {"sync": "false"}),
}

# Endpoint opcional con la lluvia de 24 h de los pluviómetros (alimenta el mapa de calor).
RUTA_LLUVIA = ("movimientos-de-masa", {})

# Nombres de la API -> nombres de columna del tablero.
RENOMBRAR = {"nivelActual": "nivel_actual", "caudalActual": "caudal_actual"}


@dataclass
class Datos:
    estaciones: pd.DataFrame
    consultado: datetime
    desde_respaldo: bool = False
    lluvia: pd.DataFrame | None = None  # None si la API no la entregó
    calor: tuple | None = None  # imagen RGBA y límites del mapa de calor, ya interpolados


def _get(ruta: str, params: dict) -> list[dict]:
    resp = requests.get(f"{BASE_URL}/{ruta}", params=params, timeout=(10, 60))
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.json()["features"]


def descargar_crudo() -> dict:
    """Consulta los cuatro endpoints de estaciones. Todos son obligatorios: si falla
    alguno se lanza la excepción, para no mostrar conteos parciales como si fueran
    completos. La lluvia es opcional: si falla, solo se pierde el mapa de calor.

    Las cinco consultas van en paralelo: en secuencia suman ~12 s (pluviómetros solo
    tarda 7 s); en paralelo, lo que tarde la más lenta."""
    consultado = datetime.now(BOGOTA).isoformat()
    with ThreadPoolExecutor(len(RUTAS) + 1) as pool:
        capas = {cat: pool.submit(_get, ruta, params) for cat, (ruta, params) in RUTAS.items()}
        lluvia = pool.submit(_get, *RUTA_LLUVIA)
        crudo = {"consultado": consultado, "capas": {c: f.result() for c, f in capas.items()},
                 "lluvia": None}
        try:
            crudo["lluvia"] = lluvia.result()
        except (requests.RequestException, ValueError, KeyError):
            pass
    return crudo


def clave(nombre: str) -> str:
    """Nombre sin tildes, espacios ni mayúsculas, para ordenar ('Don Matías' == 'Donmatías')."""
    sin_tildes = unicodedata.normalize("NFD", nombre)
    return "".join(c for c in sin_tildes if c.isalnum() and ord(c) < 128).lower()


def _texto(valor) -> str | None:
    """Texto sin espacios repetidos; None si la API lo deja vacío (en pandas, NaN)."""
    if pd.isna(valor):
        return None
    limpio = " ".join(str(valor).split())
    return limpio or None


def _fila(categoria: str, feature: dict) -> dict | None:
    coords = (feature.get("geometry") or {}).get("coordinates")
    if not coords or len(coords) < 2:
        return None
    p = {RENOMBRAR.get(k, k): v for k, v in feature["properties"].items()}
    p["nombre"] = _texto(p.pop("nombreEstacion", None) or p.pop("descripcion", None))
    p["longitud"], p["latitud"] = coords[0], coords[1]
    p["categoria"] = categoria
    return p


def _tabla_lluvia(features: list[dict] | None) -> pd.DataFrame | None:
    """Lluvia de 24 h por pluviómetro. Solo lecturas válidas: una estación con el
    dato viejo (`data_valid` falso) reporta 0 mm y apagaría la lluvia de su zona."""
    if not features:
        return None
    filas = []
    for f in features:
        coords = (f.get("geometry") or {}).get("coordinates")
        p = f["properties"]
        if not coords or len(coords) < 2:
            continue
        filas.append({
            "codigo": p["codigo"], "nombre": _texto(p.get("nombreEstacion")),
            "longitud": coords[0], "latitud": coords[1],
            "lluvia_24h": p.get("rainfall_24h"), "valido": bool(p.get("data_valid")),
            "medido": p.get("last_measurement_at"),
        })
    df = pd.DataFrame(filas)
    for col in ("longitud", "latitud", "lluvia_24h"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["medido"] = pd.to_datetime(
        df["medido"], utc=True, format="ISO8601", errors="coerce"
    ).dt.tz_convert(BOGOTA)
    return df[df["valido"]].dropna(subset=["longitud", "latitud", "lluvia_24h"]).reset_index(drop=True)


def construir(crudo: dict) -> Datos:
    filas = [
        fila
        for categoria, features in crudo["capas"].items()
        for f in features
        if (fila := _fila(categoria, f)) is not None
    ]
    df = pd.DataFrame(filas)

    df["latitud"] = pd.to_numeric(df["latitud"], errors="coerce")
    df["longitud"] = pd.to_numeric(df["longitud"], errors="coerce")
    df = df.dropna(subset=["latitud", "longitud"]).copy()

    for col in ("municipio", "region", "fuente"):
        df[col] = df[col].map(_texto)
    df["categoria_nombre"] = df["categoria"].map(NOMBRE_TIPO)
    df["municipio_nombre"] = df["municipio"].fillna(SIN_ASIGNAR)
    df["subregion"] = df["region"].fillna(SIN_ASIGNAR)
    df["activo"] = df["activo"].fillna(False).astype(bool)
    df["conectado"] = df["conectado"].fillna(False).astype(bool)

    # La lluvia de 24 h también se muestra en el popup de cada pluviómetro.
    lluvia = _tabla_lluvia(crudo.get("lluvia"))
    df["lluvia_24h"] = float("nan")
    if lluvia is not None:
        es_pluv = df["categoria"] == "PLUVIOMETROS"
        df.loc[es_pluv, "lluvia_24h"] = df.loc[es_pluv, "codigo"].map(
            lluvia.set_index("codigo")["lluvia_24h"]
        )

    for col in COLUMNAS_MEDIDA:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].where(df[col] != SENTINELA)  # -999 = sin lectura

    # Fechas ISO con y sin «Z» / microsegundos; se muestran en hora de Colombia.
    for origen, destino in (("created_at", "ultimo_dato"), ("updated_at", "actualizado")):
        df[destino] = pd.to_datetime(
            df[origen], utc=True, format="ISO8601", errors="coerce"
        ).dt.tz_convert(BOGOTA)

    df = df.sort_values(["subregion", "municipio_nombre", "codigo"]).reset_index(drop=True)
    df["primer_registro"] = pd.NaT  # lo completa instalaciones.aplicar (lee archivo y, a veces, la API)
    # `Datos.lluvia` alimenta solo el mapa de calor y su leyenda; el popup ya tomó su valor arriba.
    if lluvia is not None:
        lluvia = lluvia[~lluvia["codigo"].isin(ESTACIONES_SIN_CALOR)].reset_index(drop=True)
    return Datos(
        estaciones=df, consultado=datetime.fromisoformat(crudo["consultado"]), lluvia=lluvia
    )


def _terminar(datos: Datos, completar: bool) -> Datos:
    """Lo que no sale solo del JSON de la API: primer registro de cada estación (archivo y,
    con `completar`, la API) y el mapa de calor, que se interpola una vez y no en cada recarga."""
    import instalaciones  # aquí y no arriba: instalaciones importa este módulo

    instalaciones.aplicar(datos.estaciones, completar=completar)
    datos.calor = mapa_calor.imagen(datos.lluvia)
    return datos


def cargar_api() -> Datos:
    """Datos frescos de la API; los guarda también como respaldo. Si la API falla lanza la
    excepción. No usa la caché de Streamlit: `almacen.py` decide cuándo llamarla, en un
    hilo aparte, para que ninguna visita espere a la API."""
    crudo = descargar_crudo()
    datos = _terminar(construir(crudo), completar=True)
    SNAPSHOT.parent.mkdir(exist_ok=True)  # el respaldo solo se escribe si todo salió bien
    temporal = SNAPSHOT.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(crudo, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, SNAPSHOT)
    return datos


def cargar_respaldo() -> Datos | None:
    """Última respuesta completa guardada en disco, o None si no existe o está dañada."""
    try:
        crudo = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        datos = _terminar(construir(crudo), completar=False)  # sin red: solo lo ya guardado
    except (OSError, ValueError, KeyError):
        return None
    datos.desde_respaldo = True
    return datos
