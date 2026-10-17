"""Mapa de calor de lluvia: interpola la lluvia de 24 h de los pluviómetros a una imagen."""

import numpy as np
import pandas as pd

from catalogos import ESCALA_LLUVIA, RADIO_LLUVIA_KM

PASO = 0.01        # tamaño de celda en grados (~1,1 km)
POTENCIA = 2       # IDW: el peso de cada estación cae con el cuadrado de la distancia
PISO_KM = 0.5      # evita dividir por cero justo sobre una estación
OPACIDAD = 0.78
KM_POR_GRADO_LAT = 110.57
KM_POR_GRADO_LON_ECUADOR = 111.32

_MM = np.array([mm for mm, _ in ESCALA_LLUVIA], dtype=float)
_RGB = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in ESCALA_LLUVIA], dtype=float)


def imagen(lluvia: pd.DataFrame) -> tuple[np.ndarray, list[list[float]]] | None:
    """Imagen RGBA (norte arriba) y límites [[sur, oeste], [norte, este]] para folium.

    Interpolación de `lluvia_24h` por distancia inversa local (Shepard modificado). Es
    transparente donde no llueve y a más de RADIO_LLUVIA_KM de la estación más cercana.
    None si no hay estaciones."""
    if lluvia is None or lluvia.empty:
        return None
    lon, lat, valor = (lluvia[c].to_numpy(dtype=float) for c in ("longitud", "latitud", "lluvia_24h"))
    km_lon = KM_POR_GRADO_LON_ECUADOR * np.cos(np.radians(lat.mean()))
    margen = RADIO_LLUVIA_KM / KM_POR_GRADO_LAT

    lons = np.arange(lon.min() - margen, lon.max() + margen, PASO)
    lats = np.arange(lat.max() + margen, lat.min() - margen, -PASO)  # de norte a sur
    gx, gy = np.meshgrid(lons, lats)

    suma = np.zeros_like(gx)
    pesos = np.zeros_like(gx)
    mas_cercana = np.full_like(gx, np.inf)
    for x, y, v in zip(lon, lat, valor):
        d = np.hypot((gx - x) * km_lon, (gy - y) * KM_POR_GRADO_LAT)
        # Peso de Franke-Little: cada estación solo influye dentro del radio, así la
        # lluvia de una estación lejana no se «filtra» sobre zonas secas.
        w = (np.clip(RADIO_LLUVIA_KM - d, 0, None) / (RADIO_LLUVIA_KM * np.maximum(d, PISO_KM))) ** POTENCIA
        suma += w * v
        pesos += w
        mas_cercana = np.minimum(mas_cercana, d)
    z = np.divide(suma, pesos, out=np.zeros_like(suma), where=pesos > 0)

    rgb = np.stack([np.interp(z, _MM, _RGB[:, i]) for i in range(3)], axis=-1)
    # Transparencia: se desvanece donde la lluvia es casi nula y hacia el borde del radio.
    por_valor = np.clip((z - _MM[0]) / (2 * _MM[0]), 0, 1)
    por_borde = np.clip((RADIO_LLUVIA_KM - mas_cercana) / (0.4 * RADIO_LLUVIA_KM), 0, 1)
    alfa = OPACIDAD * por_valor * por_borde
    rgba = np.dstack([rgb, alfa * 255]).astype(np.uint8)

    limites = [[float(lats.min()), float(lons.min())], [float(lats.max()), float(lons.max())]]
    return rgba, limites


def _fmt(mm: float) -> str:
    return f"{mm:g}"


def escala_leyenda() -> list[tuple[str, str, str]]:
    """(color, valor donde empieza, rango en mm) de cada escalón, para la leyenda."""
    out = []
    for i, (mm, color) in enumerate(ESCALA_LLUVIA):
        ultimo = i + 1 == len(ESCALA_LLUVIA)
        rango = f">{_fmt(mm)}" if ultimo else f"{_fmt(mm)}–{_fmt(ESCALA_LLUVIA[i + 1][0])}"
        out.append((color, f"{_fmt(mm)}+" if ultimo else _fmt(mm), rango))
    return out
