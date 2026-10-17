"""Almacén de datos compartido por todas las visitas: ninguna espera a la API.

Al arrancar carga el último respaldo del disco (milisegundos). Si los datos tienen más de
`TTL_SEGUNDOS`, una visita lanza la actualización en un hilo aparte y todas siguen viendo los
datos guardados hasta que el hilo termina. Solo la primera vez, sin respaldo, hay que esperar.
"""

import threading
import time
from datetime import datetime

import streamlit as st

import sama_api

REINTENTO_SEG = 300  # tras un fallo, no se vuelve a intentar antes de 5 minutos


class Almacen:
    def __init__(self):
        self._candado = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._ultimo_intento = 0.0
        self.error: Exception | None = None  # fallo de la última actualización, si lo hubo
        self.datos: sama_api.Datos | None = sama_api.cargar_respaldo()

    @property
    def actualizando(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def _vencido(self) -> bool:
        if self.datos is None:
            return True
        edad = (datetime.now(sama_api.BOGOTA) - self.datos.consultado).total_seconds()
        return edad > sama_api.TTL_SEGUNDOS

    def _lanzar(self) -> None:  # con el candado tomado
        self._hilo = threading.Thread(target=self._trabajo, daemon=True, name="actualizar-datos")
        self._hilo.start()

    def _trabajo(self) -> None:
        try:
            datos = sama_api.cargar_api()
            with self._candado:
                self.datos, self.error = datos, None
        except Exception as exc:  # la API puede fallar de muchas formas; se conservan los datos viejos
            with self._candado:
                self.error = exc
        finally:
            self._ultimo_intento = time.time()

    def actualizar_si_hace_falta(self) -> None:
        with self._candado:
            if (not self.actualizando and self._vencido()
                    and time.time() - self._ultimo_intento > REINTENTO_SEG):
                self._lanzar()

    def esperar(self) -> None:
        hilo = self._hilo
        if hilo is not None:
            hilo.join()

    def forzar(self) -> None:
        """Actualiza ya y espera el resultado (botón «Actualizar ahora»)."""
        with self._candado:
            if not self.actualizando:
                self._lanzar()
        self.esperar()


@st.cache_resource
def _unico() -> Almacen:
    return Almacen()


def obtener() -> Almacen:
    almacen = _unico()
    almacen.actualizar_si_hace_falta()
    return almacen
