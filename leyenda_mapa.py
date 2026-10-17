"""Leyenda plegable dentro del mapa de folium (control de Leaflet, debajo del selector de capas)."""

import json

import folium
from branca.element import MacroElement, Template

# Estilos del control; viven dentro del iframe del mapa, no en la página de Streamlit.
CSS = """<style>
.leyenda-mapa {background: rgba(255,255,255,.96); border-radius: 8px; padding: 6px 10px;
    box-shadow: 0 1px 6px rgba(0,0,0,.35); max-width: 300px; color: #0B2A4A;
    font: 12px/1.55 "Helvetica Neue", Arial, sans-serif;}
.leyenda-mapa summary {cursor: pointer; font-weight: 700; font-size: 13px; list-style: none;
    user-select: none; outline: none;}
.leyenda-mapa summary::-webkit-details-marker {display: none;}
.leyenda-mapa summary::before {content: "\\25BE"; margin-right: 5px;}
.leyenda-mapa details:not([open]) summary::before {content: "\\25B8";}
.leyenda-mapa h4 {margin: 7px 0 3px; padding-top: 5px; border-top: 1px solid #D5DBE3; font-size: 12px;}
.leyenda-mapa .punto {display: inline-block; width: 11px; height: 11px; border-radius: 50%;
    margin-right: 6px; vertical-align: -1px; box-sizing: border-box;}
.leyenda-mapa .escala {display: flex;}
.leyenda-mapa .escala div {width: 27px;}
.leyenda-mapa .escala .chip {display: block; height: 9px;}
.leyenda-mapa .escala small {font-size: 10px; color: #44546A;}
.leyenda-mapa .nota {margin-top: 3px; max-width: 270px; font-size: 11px; color: #44546A;}
</style>"""


class _Leyenda(MacroElement):
    # Recuerda en el navegador si el usuario la dejó plegada, para que no se reabra al
    # cambiar un filtro (cada cambio vuelve a dibujar el mapa). Mientras no haya elegido,
    # en pantallas angostas (celular) empieza plegada porque taparía casi todo el mapa.
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
            var control = L.control({position: 'topright'});
            control.onAdd = function () {
                var div = L.DomUtil.create('div', 'leyenda-mapa');
                div.innerHTML = {{ this.html_json }};
                var detalle = div.querySelector('details');
                try {
                    var elegida = localStorage.getItem('sama-leyenda');
                    var ancho = window.innerWidth;
                    try { ancho = window.parent.innerWidth; } catch (e) {}
                    if (elegida === 'plegada' || (elegida === null && ancho < 640)) { detalle.open = false; }
                    // Se guarda solo al hacer clic: el evento `toggle` también salta al dibujarla.
                    detalle.querySelector('summary').addEventListener('click', function () {
                        setTimeout(function () {
                            localStorage.setItem('sama-leyenda', detalle.open ? 'abierta' : 'plegada');
                        }, 0);
                    });
                } catch (e) {}
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.disableScrollPropagation(div);
                return div;
            };
            control.addTo({{ this._parent.get_name() }});
        })();
        {% endmacro %}
    """)

    def __init__(self, html: str):
        super().__init__()
        self._name = "LeyendaMapa"
        # `</` cerraría el <script> que contiene este texto.
        self.html_json = json.dumps(html, ensure_ascii=False).replace("</", "<\\/")


def agregar(mapa: folium.Map, html: str) -> None:
    """Añade al mapa una leyenda plegable con el HTML dado, que debe ser un <details open>."""
    mapa.get_root().header.add_child(folium.Element(CSS))
    _Leyenda(html).add_to(mapa)
