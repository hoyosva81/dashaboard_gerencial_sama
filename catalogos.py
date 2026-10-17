"""Constantes de presentación del tablero SAMA (API de estaciones en GeoJSON).

La API entrega municipio y región como texto en cada estación, así que aquí no
hay tablas de códigos: solo el orden, los nombres y colores de cada categoría
(una por endpoint) y los campos que se muestran en el popup del mapa.
"""

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre")

# Texto que se usa cuando la API deja vacío el municipio o la región (decisión del usuario).
SIN_ASIGNAR = "Sin asignar"

# La API manda -999 cuando el sensor no entrega lectura (calidad 2).
SENTINELA = -999.0

# Orden de presentación (el de los endpoints), nombre visible y color de cada categoría.
TIPOS_ORDEN = ["NIVELES", "METEOROLOGIA", "PLUVIOMETROS", "ALARMAS"]
NOMBRE_TIPO = {
    "NIVELES": "Sensores de Nivel",
    "METEOROLOGIA": "Meteorología",
    "PLUVIOMETROS": "Pluviómetros",
    "ALARMAS": "Alarmas",
}
COLOR_TIPO = {
    "NIVELES": "#FF7F0E",
    "METEOROLOGIA": "#2CA02C",
    "PLUVIOMETROS": "#1F77B4",
    "ALARMAS": "#D62728",
}
COLOR_TIPO_OTRO = "#7F7F7F"

# Categorías cuya conexión no se señala: no aporta información (decisión del usuario).
TIPOS_SIN_CONEXION = {"ALARMAS"}

# Columnas de medición que trae cada categoría -> (columna, etiqueta) para el popup.
# La API no documenta unidades; solo se indican las que no dejan duda.
CAMPOS_POPUP = {
    "NIVELES": [
        ("fuente", "Fuente"),
        ("nivel_actual", "Nivel actual"),
        ("caudal_actual", "Caudal actual"),
        ("calidad", "Calidad"),
    ],
    "METEOROLOGIA": [
        ("temperatura", "Temperatura (°C)"),
        ("humedad_relativa", "Humedad relativa (%)"),
        ("precipitacion", "Precipitación"),
        ("radiacion", "Radiación"),
        ("velocidad_viento", "Velocidad del viento"),
        ("direccion_viento", "Dirección del viento (°)"),
    ],
    "PLUVIOMETROS": [
        ("lluvia_24h", "Lluvia 24 h (mm)"),
        ("sum_amarillo", "Suma amarillo"),
        ("sum_naranja", "Suma naranja"),
        ("sum_rojo", "Suma rojo"),
    ],
    "ALARMAS": [
        ("estado", "Estado"),
        ("calidad", "Calidad"),
    ],
}

# Mapa de calor de lluvia: (mm en 24 h, color) de cada escalón. Por debajo del primero
# no se pinta nada. Los escalones son más finos en lluvias bajas, que son las comunes.
ESCALA_LLUVIA = [
    (0.1, "#CFE8F7"), (1, "#8CCBEF"), (2.5, "#4AA8E3"), (5, "#2A7FD1"), (10, "#2BAE66"),
    (20, "#F2D43D"), (35, "#F28C28"), (50, "#E03C31"), (75, "#B0227A"), (100, "#6A1B9A"),
]
# Más allá de esta distancia a la estación más cercana no se interpola (no hay dato).
RADIO_LLUVIA_KM = 35
# Pluviómetros cuya lectura se descarta del mapa de calor y de su leyenda (decisión del usuario).
ESTACIONES_SIN_CALOR = {"sp_176"}  # Volcán de lodo - El Aburrido

# Todas las columnas numéricas donde puede aparecer el valor centinela.
COLUMNAS_MEDIDA = sorted({c for campos in CAMPOS_POPUP.values() for c, _ in campos} - {"fuente", "calidad"})
