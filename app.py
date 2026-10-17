"""Tablero SAMA: estaciones de monitoreo de Antioquia (datos de la API de SAMA)."""

import html
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

import almacen
import leyenda_mapa
import mapa_calor
import sama_api
from catalogos import (
    CAMPOS_POPUP, COLOR_TIPO, COLOR_TIPO_OTRO, MESES, NOMBRE_TIPO, SIN_ASIGNAR,
    TIPOS_ORDEN, TIPOS_SIN_CONEXION,
)

ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="SAMA · Estaciones", page_icon="📍", layout="wide")

st.markdown(
    """
    <style>
    /* El padding superior deja los recuadros justo debajo de la barra fija de Streamlit (60 px). */
    .block-container {padding-top: 2.9rem; padding-bottom: 1rem; max-width: 100%;}
    .kpi {text-align: center; padding: .6rem 0 .2rem;}
    .kpi .valor {font-size: clamp(2.4rem, 3vw, 3.4rem); font-weight: 500; line-height: 1.05;}
    .kpi .etiqueta {font-size: clamp(.8rem, 1vw, 1.1rem); line-height: 1.3; margin-top: .4rem;
                    min-height: 2.6em;
                    display: flex; align-items: center; justify-content: center;}
    .total {display: flex; justify-content: space-between; font-weight: 700;
            padding: .3rem .8rem; border-top: 2px solid #C9D1DA;}
    div[data-testid="stImage"] {display: flex; justify-content: center;}
    /* Encabezado compacto: recuadros con poco relleno y menos espacio hacia el cuerpo. */
    .st-key-logo-sama, .st-key-logo-eafit {
        padding: .3rem .6rem !important; min-height: 3.5rem; justify-content: center;}
    .st-key-encabezado {margin-bottom: -.5rem;}
    .st-key-filtro-mes p {font-size: .875rem; margin: 0 0 .25rem;}

    /* Vista móvil (Streamlit apila las columnas por debajo de 640 px). */
    @media (max-width: 640px) {
        .block-container {padding: 3.6rem .7rem .5rem;}
        .st-key-encabezado [data-testid="stHorizontalBlock"] {flex-wrap: nowrap; gap: .4rem;}
        .st-key-encabezado [data-testid="stColumn"] {min-width: 0 !important; width: auto !important;}
        .st-key-encabezado [data-testid="stColumn"]:first-child {flex: 0 0 36% !important;}
        .st-key-encabezado [data-testid="stColumn"]:last-child {flex: 1 1 0 !important;}
        .st-key-encabezado [data-testid="stImage"], .st-key-encabezado img {
            width: 100% !important; max-width: 100%; height: auto;}
        .st-key-kpis [data-testid="stHorizontalBlock"] {flex-wrap: wrap; gap: .4rem;}
        .st-key-kpis [data-testid="stColumn"] {   /* cuadrícula de 2 × 2 */
            min-width: 0 !important; width: calc(50% - .2rem) !important;
            flex: 0 0 calc(50% - .2rem) !important;}
        .kpi .valor {font-size: 2.1rem;}
        .kpi .etiqueta {font-size: .85rem;}
        iframe[title="streamlit_folium.st_folium"] {height: 62vh !important; min-height: 360px;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def obtener_datos(alm: almacen.Almacen) -> sama_api.Datos:
    """Datos que ya hay en el almacén; solo espera si es la primera vez y no hay respaldo."""
    if alm.datos is None:
        with st.spinner("Consultando la API de SAMA…"):
            alm.esperar()
    if alm.datos is None:
        st.error(f"No se pudo consultar la API de SAMA y no hay datos guardados: {alm.error}")
        st.stop()
    if alm.error is not None:  # la última actualización falló: no se cae el tablero
        st.warning(
            f"No se pudo actualizar desde la API de SAMA ({type(alm.error).__name__}). "
            f"Se muestran los datos guardados el {alm.datos.consultado:%d/%m/%Y %H:%M}."
        )
    return alm.datos


def encabezado() -> None:
    with st.container(key="encabezado"):
        izq, der = st.columns([11, 9])  # mismas proporciones que el mapa y el panel derecho
        with izq.container(border=True, key="logo-sama"):
            st.image(str(ASSETS / "logo.svg"), width=150)
        with der.container(border=True, key="logo-eafit"):
            st.image(str(ASSETS / "EAFIT_DAGRAN.png"), width=215)


def fmt_fecha(valor) -> str:
    return "—" if pd.isna(valor) else valor.strftime("%d/%m/%Y %H:%M")


def fmt_dia(valor) -> str:
    return "—" if pd.isna(valor) else valor.strftime("%d/%m/%Y")


def mes_de(fechas: pd.Series) -> pd.Series:
    """Mes «AAAA-MM» (hora de Colombia) de cada fecha; vacío donde no hay fecha."""
    return fechas.dt.tz_localize(None).dt.strftime("%Y-%m")


def etiqueta_mes_corta(mes: str) -> str:
    """«oct 2026»: cabe en dos líneas dentro de una tarjeta KPI."""
    return f"{MESES[int(mes[5:]) - 1][:3]} {mes[:4]}"


def txt(valor) -> str:
    """Texto seguro para HTML; la API deja campos vacíos (NaN en pandas)."""
    if pd.isna(valor) or valor == "":
        return "—"
    if isinstance(valor, float):
        return f"{valor:.4f}".rstrip("0").rstrip(".")
    return html.escape(str(valor))


def si_no(valor: bool) -> str:
    return "Sí" if valor else "No"


def sin_conexion(df: pd.DataFrame) -> pd.Series:
    """Estaciones desconectadas, sin contar las categorías cuya conexión no se señala."""
    return ~df.conectado & ~df.categoria.isin(TIPOS_SIN_CONEXION)


# (nombre, url, atribución, zoom máximo). El primero se muestra por defecto.
MAPAS_BASE = [
    ("Esri Topográfico",
     "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
     "Tiles © Esri", 19),
    ("Esri Gris claro",
     "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
     "Tiles © Esri", 16),
    ("OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
     "© OpenStreetMap contributors", 19),
]


def popup(e) -> str:
    medidas = "".join(
        f"<b>{etiqueta}:</b> {txt(getattr(e, col))}<br>"
        for col, etiqueta in CAMPOS_POPUP.get(e.categoria, [])
    )
    conexion = (
        "" if e.categoria in TIPOS_SIN_CONEXION
        else f"<b>Conectada:</b> {si_no(e.conectado)}<br>"
    )
    return (
        f"<b>{txt(e.codigo)}</b><br>{txt(e.nombre)}<br>"
        f"<i>{txt(e.categoria_nombre)}</i><hr style='margin:4px 0'>"
        f"<b>Municipio:</b> {txt(e.municipio_nombre)}<br>"
        f"<b>Subregión:</b> {txt(e.subregion)}<br>{medidas}"
        f"<b>Activa:</b> {si_no(e.activo)}<br>"
        f"{conexion}"
        f"<b>Primer registro:</b> {fmt_dia(e.primer_registro)}<br>"
        f"<b>Último dato:</b> {fmt_fecha(e.ultimo_dato)}<br>"
        f"<b>Actualizada:</b> {fmt_fecha(e.actualizado)}"
    )


def estilo_marcador(e) -> dict:
    """Conectada: borde blanco. Sin conexión: borde negro. Inactiva: relleno tenue y borde punteado.
    En las categorías de TIPOS_SIN_CONEXION no se distingue la conexión."""
    if not e.activo:
        return dict(color="#555555", weight=2, dash_array="3 3", fill_opacity=0.3)
    if not e.conectado and e.categoria not in TIPOS_SIN_CONEXION:
        return dict(color="#000000", weight=3, fill_opacity=0.95)
    return dict(color="#FFFFFF", weight=1.5, fill_opacity=0.95)


def leyenda_html(f: pd.DataFrame, tipos: list[str], lluvia: pd.DataFrame | None) -> str:
    """Contenido de la leyenda plegable del mapa; solo lista lo que hay en pantalla."""
    por_tipo = f.groupby("categoria").size()
    html_ = "".join(
        f'<div><span class="punto" style="background:{COLOR_TIPO.get(t, COLOR_TIPO_OTRO)}"></span>'
        f"{NOMBRE_TIPO[t]} <b>{int(por_tipo.get(t, 0))}</b></div>"
        for t in tipos
    )
    if sin_conexion(f).any():
        html_ += ('<div><span class="punto" style="background:#DDD;border:3px solid #000"></span>'
                  "Sin conexión</div>")
    if not f.activo.all():
        html_ += ('<div><span class="punto" style="background:#DDD;opacity:.5;'
                  'border:2px dashed #555"></span>Inactiva</div>')

    if lluvia is not None and not lluvia.empty:
        maxima = lluvia.loc[lluvia.lluvia_24h.idxmax()]
        resumen = (
            f"máx. {txt(float(maxima.lluvia_24h))} mm ({txt(maxima.codigo)})"
            if maxima.lluvia_24h > 0 else "sin lluvia en las últimas 24 h"
        )
        escala = "".join(
            f'<div title="{rango} mm"><span class="chip" style="background:{color}"></span>'
            f"<small>{desde}</small></div>"
            for color, desde, rango in mapa_calor.escala_leyenda()
        )
        html_ += (
            f'<h4>Lluvia 24 h (mm)</h4><div class="escala">{escala}</div>'
            f'<div class="nota">Interpolado con {len(lluvia)} pluviómetros · {resumen} · '
            f"lectura {fmt_fecha(lluvia.medido.max())}</div>"
        )
    return f"<details open><summary>Leyenda</summary>{html_}</details>"


def mapa(f: pd.DataFrame, tipos: list[str], lluvia: pd.DataFrame | None,
         calor: tuple | None) -> folium.Map:
    m = folium.Map(
        location=[6.9, -75.5], zoom_start=8, tiles=None, control_scale=True,
        prefer_canvas=True,
    )
    for i, (nombre, url, atribucion, zoom_max) in enumerate(MAPAS_BASE):
        folium.TileLayer(
            tiles=url, attr=atribucion, name=nombre, max_zoom=zoom_max, show=(i == 0)
        ).add_to(m)

    # El mapa de calor (ya interpolado en el almacén) va antes que los marcadores para quedar debajo.
    if calor:
        rgba, limites = calor
        folium.raster_layers.ImageOverlay(
            image=rgba, bounds=limites, name="Lluvia 24 h (mapa de calor)",
            origin="upper", interactive=False, show=True,
        ).add_to(m)

    grupos = {t: folium.FeatureGroup(name=NOMBRE_TIPO[t]).add_to(m) for t in tipos}
    for e in f.itertuples():
        etiqueta = e.codigo if pd.isna(e.nombre) else f"{e.codigo} · {e.nombre}"
        folium.CircleMarker(
            [e.latitud, e.longitud], radius=6, fill=True,
            fill_color=COLOR_TIPO.get(e.categoria, COLOR_TIPO_OTRO),
            tooltip=f"{etiqueta} ({e.categoria_nombre})",
            popup=folium.Popup(popup(e), max_width=300),
            **estilo_marcador(e),
        ).add_to(grupos[e.categoria])

    folium.LayerControl(collapsed=True).add_to(m)
    leyenda_mapa.agregar(m, leyenda_html(f, tipos, lluvia))
    if len(f):
        m.fit_bounds(
            [[f.latitud.min(), f.longitud.min()], [f.latitud.max(), f.longitud.max()]],
            padding=(30, 30), max_zoom=11,
        )
    return m


def grafico_tipos(conteo: pd.Series, tipos: list[str]) -> go.Figure:
    valores = [int(conteo.get(t, 0)) for t in tipos]
    fig = go.Figure(
        go.Bar(
            x=valores, y=[NOMBRE_TIPO[t] for t in tipos], orientation="h",
            marker_color=[COLOR_TIPO.get(t, COLOR_TIPO_OTRO) for t in tipos],
            text=valores, textposition="outside",
            cliponaxis=False, hovertemplate="%{y}: %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        height=280, margin=dict(l=0, r=30, t=10, b=0), bargap=0.35,
        yaxis=dict(autorange="reversed"),
        xaxis=dict(rangemode="tozero", gridcolor="#E3E7EC"),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def tabla_conteo(f: pd.DataFrame, columna: str, titulo: str, col_nro: str) -> None:
    c = f.groupby(columna).size().rename(col_nro).reset_index()
    c = c.rename(columns={columna: titulo}).sort_values(
        [col_nro, titulo], ascending=[False, True]
    )
    st.dataframe(
        c, hide_index=True, height=320, width="stretch",
        column_config={col_nro: st.column_config.NumberColumn(col_nro, format="%d")},
    )
    st.markdown(
        f'<div class="total"><span>Total</span><span>{int(c[col_nro].sum())}</span></div>',
        unsafe_allow_html=True,
    )


def orden_nombre(nombre: str) -> tuple:
    """Alfabético sin tildes y con «Sin asignar» al final."""
    return (nombre == SIN_ASIGNAR, sama_api.clave(nombre))


# ---------------------------------------------------------------- aplicación
encabezado()
alm = almacen.obtener()
datos = obtener_datos(alm)
df = datos.estaciones

tipos = [t for t in TIPOS_ORDEN if t in set(df.categoria)]

with st.sidebar:
    st.header("Filtros")
    sel_tipos = st.multiselect(
        "Tipo de estación", tipos, format_func=NOMBRE_TIPO.get, placeholder="Todos"
    )
    sel_sub = st.multiselect(
        "Subregión", sorted(df.subregion.unique(), key=orden_nombre), placeholder="Todas"
    )
    base = df[df.subregion.isin(sel_sub)] if sel_sub else df
    # Sin `key`: la selección se reinicia sola cuando cambia la subregión.
    sel_mun = st.multiselect(
        "Municipio", sorted(base.municipio_nombre.unique(), key=orden_nombre),
        placeholder="Todos",
    )
    # Solo afecta la tarjeta «Instaladas…»; no filtra el mapa ni las tablas. Año y mes van
    # por separado: una lista de todos los meses desde 2020 sería demasiado larga.
    hoy = pd.Timestamp.now(sama_api.BOGOTA)
    anios = sorted({int(m[:4]) for m in mes_de(df["primer_registro"]).dropna()} | {hoy.year},
                   reverse=True)
    with st.container(key="filtro-mes"):
        st.markdown(
            "Mes de instalación",
            help="Cuenta las estaciones cuyo primer registro de datos cae en ese mes. "
                 "La API no informa la fecha de instalación.",
        )
        col_anio, col_mes = st.columns(2)
        anio = col_anio.selectbox("Año", anios, label_visibility="collapsed")
        meses = list(range(1, (hoy.month if anio == hoy.year else 12) + 1))  # sin meses futuros
        mes = col_mes.selectbox(
            "Mes", meses, index=hoy.month - 1, label_visibility="collapsed",
            format_func=lambda m: MESES[m - 1].capitalize(),
        )
    sel_mes = f"{anio}-{mes:02d}"
    sin_registros = int(df["primer_registro"].isna().sum())
    if sin_registros:
        st.caption(
            f"{sin_registros} estación sin registros de datos no se cuenta." if sin_registros == 1
            else f"{sin_registros} estaciones sin registros de datos no se cuentan."
        )
    st.divider()
    st.caption(f"Última actualización de los datos: {datos.consultado:%d/%m/%Y %H:%M}")
    if alm.actualizando:
        st.caption("Actualizando en segundo plano…")
    if st.button("Actualizar ahora", width="stretch"):
        with st.spinner("Consultando la API de SAMA…"):
            alm.forzar()
        st.rerun()

f = df
if sel_tipos:
    f = f[f.categoria.isin(sel_tipos)]
if sel_sub:
    f = f[f.subregion.isin(sel_sub)]
if sel_mun:
    f = f[f.municipio_nombre.isin(sel_mun)]
por_tipo = f.groupby("categoria").size()

col_mapa, col_der = st.columns([11, 9])

with col_mapa:
    with st.container(border=True):
        st_folium(
            mapa(f, tipos, datos.lluvia, datos.calor), height=720, use_container_width=True,
            returned_objects=[], key="mapa",
        )

with col_der:
    with st.container(key="kpis"):
        k1, k2, k3, k4 = st.columns(4)
        hay_registro = df["primer_registro"].notna().any()  # sin archivo de primer registro: «—»
        for col, valor, etiqueta in (
            (k1, len(f), "Estaciones"),
            (k2, f.loc[f.municipio_nombre != SIN_ASIGNAR, "municipio_nombre"].nunique(),
             "Municipios monitoreados"),
            (k3, int(sin_conexion(f).sum()), "Sin conexión"),
            (k4, int((mes_de(f["primer_registro"]) == sel_mes).sum()) if hay_registro else "—",
             f"Instaladas<br>{etiqueta_mes_corta(sel_mes)}"),
        ):
            with col.container(border=True):
                st.markdown(
                    f'<div class="kpi"><div class="valor">{valor}</div>'
                    f'<div class="etiqueta">{etiqueta}</div></div>',
                    unsafe_allow_html=True,
                )

    with st.container(border=True):
        st.plotly_chart(
            grafico_tipos(por_tipo, tipos), width="stretch",
            config={"displayModeBar": False},
        )

    t1, t2 = st.columns(2)
    with t1:
        tabla_conteo(f, "subregion", "Subregión", "Nro estaciones")
    with t2:
        tabla_conteo(f, "municipio_nombre", "Municipio", "Nro. estaciones")

with st.expander("Detalle de estaciones"):
    detalle = f[
        ["codigo", "nombre", "categoria_nombre", "municipio_nombre", "subregion",
         "fuente", "activo", "conectado", "latitud", "longitud", "primer_registro",
         "ultimo_dato", "actualizado"]
    ].copy()
    detalle["activo"] = detalle["activo"].map(si_no)
    detalle["conectado"] = detalle["conectado"].map(si_no).where(
        ~f.categoria.isin(TIPOS_SIN_CONEXION), "—"
    )
    detalle["primer_registro"] = detalle["primer_registro"].map(fmt_dia)
    detalle["ultimo_dato"] = detalle["ultimo_dato"].map(fmt_fecha)
    detalle["actualizado"] = detalle["actualizado"].map(fmt_fecha)
    detalle.columns = [
        "Código", "Nombre", "Tipo", "Municipio", "Subregión", "Fuente", "Activa", "Conectada",
        "Latitud", "Longitud", "Primer registro", "Último dato", "Actualizada",
    ]
    st.dataframe(detalle, hide_index=True, width="stretch")
    st.download_button(
        "Descargar CSV", detalle.to_csv(index=False).encode("utf-8-sig"),
        file_name="estaciones_sama.csv", mime="text/csv",
    )

st.caption(
    "Fuente: API de SAMA (sama-dagran.duckdns.org), DAGRAN · Gobernación de Antioquia. "
    f"Las estaciones sin municipio o subregión en la API aparecen como «{SIN_ASIGNAR}». "
    "El mapa de calor es una estimación interpolada entre pluviómetros (hasta 35 km de la "
    "estación más cercana), no una medición continua."
)
