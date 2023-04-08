from datetime import date

import PySimpleGUI as sg
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

from .log_tools import *

FORMA_PAGO = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_FormaPago']
TEXT_PADDING = ((5, 0), 3)
RTEXT_PADDING = ((0, 0), 3)

# 24 x 24
FOLDER_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAAqElEQVR4nO3UsQnCYBRF4U/EAcRJtHUJcQddwQlsxcpVLF0hOoY2FlaC+SUQQWI0PmwscuF0j3PhFZc2" \
              "/5QR9siRnjhhid6vBVlFXGWHwS8Ft4aCHLPydozFGybo1BV8kl8wLe/muDbcryIFBwzRxbpB/OAcfV8f2y/lD17y7qcbHIPy2oKoILUFqX1RdCpSgMIVHrsUoHDVznVWM9cpQF46imlp8ye5AyE7C1To4" \
              "/HLAAAAAElFTkSuQmCC"

EXCEL_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAA7klEQVR4nN2VQQqCUBCGv2pfFyhv0FmC7hGFq1bhrgi6gi1cBK6CdhFtvYdCi6CgrZsXwgTyUNOnLmrgBx31" \
             "/+DNOAP/HkNgCqyBK3AHLsDA1HAELIEjcANUjuYm5hbwKDBVKTnyjZ5/ATugkwWwS5qrAsBHkyyA0yBg1SQgAraiSHueCwgBL3V" \
             "/kFwWwAd6Ir8swJXcSZTEvsIRfQXEwFg6y5LruElAogDoioKma1AF4JvUoPUjctsucqi1qVfQpsY1KPuj+SY1qDsqnLaH3SJvF9Qd1wp4ilethTOT9zea7CLzsivzDPSrmPx2vAFRfA9plcmcVwAAAABJRU5ErkJggg=="

HTML_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAA/ElEQVR4nN2VOwoCMRCGPz2HB7ARHyfwBN5EsLOxWKzs7Ox0e69gYbOtoK2dZ7BVRwZGWJbsJvuw0IGfDUkmX" \
            "/gzm8A/xgi4AC9AHNLo1gGccxaWFCAC1lUBz0CAVIVICYAYpPVNgJSF+ABtYOHoXzcF6AMdYAmsMuo1ATgZpJTvZQAScEa5ETcAiIsA+vcmDm9XgUpsjUJ7tASnGV1tTL8z26VeKTdgAOwz5esFqA6mKDX2WUR3ebe" \
            "+MXCsAkhMLsAGmNQBZC3C7MHRpxY9rO0FvMyWeUUdfIe8a6BMt9S8rqVAmlv7wZECaa43RjYx78kUh3Su5gxDAL8Vb7wE7yjidnvCAAAAAElFTkSuQmCC"

SEARCH_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABM0lEQVR4nO3Uuy4FURTG8Z8gqOWcROMFKIiCkgcgUYsXELS8wYn" \
              "+FMILEJd4Bg0R1VGoNCoJnWvjkpE1yeTEsMel80+mmOxvrW/ttffa/PMD+rCMQ1zjCRfYwJgfMo5LvJZ8L2ii+7vJHyLRMWbRjx4MoYH7WN9BR9W25JWvo7NEN4Kb0C1UMVguVF6WPGc6tFfokshhBGVtSaEV" \
              "+qlUg3zbWc9TaIZ+MdXgMQJ6E/WN0K+mGlxEwHCifi/086kGmxGQVfYVNdziGYOpBmMxRNk9H/1El939rSjmQEXyg8sOfKak8u3CVGeDWYls/HcLCVphuoZ93LU9G2eoVzXpiAm9" \
              "+uAdeo62TETyb5uICZ3EElYw13ag9d8w+YpaYaLPMeAPqBd2cvIXBrnJKY7e//6RyBvdy1w1bgRSawAAAABJRU5ErkJggg=="

PDF_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAA+0lEQVR4nN3VPUrEQBQA4E89gCBio7WI" \
           "+INbeAbxAoI3ESzEysoFd21tbe28QixE7a2t7dxGRwKvWCTrTpJNoQ9ek5k3X8hM5vEfo4cXfCFVZBkbbYDnCQunMeAM" \
           "/abAZyaQmiKpBpACmesSSHWRacA8Tiue92cF7GIN57j4kduzAB4DqfXdc4ACQ3xk7FEjYBk7GHQFrOMQl10BJ3GC7roC3mL8vivgNsYXsYmlyKIt8IojLOAYV1jFQWz6sA1QxOnZwv7YFf6OG1xj1AYYRH9YwVPGT5jqXtejeMuHzMXL2tYNJ/2SZe3U6MXESS0zVWQ5t6zZywH+VnwDCQv1frFQIlYAAAAASUVORK5CYII="

DOWNLOAD_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAA2ElEQVR4nO2SPQrCQBSEv8r0AYPeQ2xyHw8QC4vUovfJDUQJRistvEBstdUqEphACMvmx6TLwINl3" \
                "+x87L6FUT3rDMQMqEw1AoZ9ojmwAjbAGnAtAFeejc7M6sKXwLsUlAGBBRBUvC9gYQOcZIyAPRA2uEEob6Te0Qb4yuR0mIGj3scGMAUcgCvglfqe9uK2n8BkSLR3L/WLddIHYArcKsPM62H4NZ0AJogp" \
                "/C8AeveLKl/TN6CJas8/ZfBpL19nU5tpZxhm1rK2NsBEkOImWYtKFZ5njKKxfvMPfI7/rbo+AAAAAElFTkSuQmCC"

GRID_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAAZElEQVR4nGNgGAUkAgEGBgYHCrEAPgtACv5TiB2IsaAAyUUXoJiQywtIsQBZ0QEoJgQcBpUFF5AM" \
            "/gDFBwjgC4PKAgdaB5HDqAW4wGgQ/R80qaiA1oXdf1oV1wK0rnBGAQM6AADMiIAFF68RXgAAAABJRU5ErkJggg="

ABOUT_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABP0lEQVR4nOWVTU7DMBCFvxuwKmrX0G4o5QLtQboDFXEbwrLkGNDucwB" \
             "+VvQObS5ApCxAIz1LCNmOG68QTxopst882y/jMfwHnAIroAQ2ilJjgxzhkYRa4AvYA6" \
             "+KvcZacYx7FBZADXwC98DUw7GxAmjEXRwjbkkfwHkCfyyu5cy7yCPtxhJOUnckruUcgGGMWMqWs8D8UhE6iZ3iMVYtrTwPoVKEUEjDW123qowL" \
             "+uNSGjche6z8YlhGLHI4hGzaAi8dyVWHReiePPsmNprMXeAdeOprUZWwQB2yaKUfNM1Y4Eoa17EyLTIWeIiVqbOp0aXx4U7hw0S565RWsevRKnYpreJ3sxsniE8kntTsHObaTaN" \
             "/MvNwZvK8ETdZ3GGocnMPjom8KeofD846xZYYBuotJmQ31MK+bSzryfwb+AbymF7gpXVM1QAAAABJRU5ErkJggg=="

BUTTON_COLOR = (sg.theme_background_color(), sg.theme_background_color())


def make_layout(has_fiel):
    # LAYOUT
    button_column = [
        sg.Button("Emitidas", key="facturas_emitidas", border_width=0),
        sg.Text("Año-Mes:", pad=TEXT_PADDING),
        sg.Input(date.today().strftime('%Y-%m'), size=(11, 1), key="periodo"),
        sg.Button(image_data=EXCEL_ICON, key="ver_excel", border_width=0, button_color=BUTTON_COLOR),
        sg.Button(image_data=HTML_ICON, key="ver_html", border_width=0, button_color=BUTTON_COLOR),
        sg.Button(image_data=FOLDER_ICON, key="ver_carpeta", border_width=0, button_color=BUTTON_COLOR),

        sg.VSeparator(),
        sg.Button("Preparar", key="prepare_facturas", border_width=0),
        sg.Text("De La:", pad=TEXT_PADDING),
        sg.Input("1", key="inicio", size=(4, 1)),
        sg.Text("Hasta:", pad=TEXT_PADDING),
        sg.Input("", key="final", size=(4, 1)),

        sg.VSeparator(),
        sg.Button("Ajustes", key="preparar_ajuste_anual", border_width=0),
        sg.Button(image_data=FOLDER_ICON, key="ver_carpeta_ajustes", border_width=0, button_color=BUTTON_COLOR),

        sg.Push(),
        sg.Text("Serie:", pad=TEXT_PADDING),
        sg.Text("", key="serie", pad=TEXT_PADDING),
        sg.Text("Folio:", pad=TEXT_PADDING),
        sg.Input("", key="folio", size=(10, 1), enable_events=True),
    ]
    c_second = [
        sg.Column(
            [
                [
                    sg.Button(image_data=SEARCH_ICON, key="buscar_factura", border_width=0, pad=TEXT_PADDING, button_color=BUTTON_COLOR),
                    sg.Input("", size=(40, 1), key="factura_pagar"),
                    sg.Button(image_data=DOWNLOAD_ICON, key="descarga", border_width=0, disabled=True, button_color=BUTTON_COLOR),
                    sg.Button(image_data=PDF_ICON, key="ver_factura", border_width=0, disabled=True, button_color=BUTTON_COLOR),
                ],
                [
                    sg.Button(" ", border_width=0, visible=True, button_color=BUTTON_COLOR),
                    sg.Button(key="status_sat", border_width=0, visible=False),
                    sg.Button(key="email_notificada", border_width=0, visible=False),
                    sg.Button(key="pendiente_pago", border_width=0, visible=False),
                ]
            ],
            pad=0
        ),
        sg.VSeparator(),
        sg.Column(
            [
                [
                    sg.CalendarButton("FechaPago:", format='%Y-%m-%d', title="FechaPago", no_titlebar=False, target="fecha_pago", pad=TEXT_PADDING, border_width=0,
                                      key="fecha_pago_select", disabled=True),
                    sg.Input("", size=(12, 1), key="fecha_pago", disabled=True),
                    sg.Text("FormaPago:", pad=TEXT_PADDING),
                    sg.Combo([Code(k, v) for k, v in FORMA_PAGO.items()], default_value=Code("03", FORMA_PAGO["03"]), key="forma_pago", size=(34, 1),
                             disabled=True),
                ],
                [
                    sg.Button("Comprobante Pago", key="prepare_pago", border_width=0, disabled=True),
                    sg.Text("       ImpPagado:", pad=TEXT_PADDING),
                    sg.Input("", size=(12, 1), key="importe_pago", disabled=True),
                ]
            ],
            pad=0
        )
    ]

    button_column_third = [
        sg.Button("Correos", key="prepare_correos", border_width=0),
        sg.Button("Pendientes", key="facturas_pendientes", border_width=0),
        sg.Button("Clientes", key="prepare_clientes", border_width=0),
        sg.VSeparator(),
        sg.Text("Recuperar:", pad=TEXT_PADDING, visible=has_fiel),
        sg.Button("Emitidas", key="recuperar_emitidas", border_width=0, visible=has_fiel),
        sg.Button("Recibidas", key="recuperar_recibidas", border_width=0, visible=has_fiel),
        sg.Text("Dias:", pad=TEXT_PADDING, visible=has_fiel),
        sg.Input("40", size=(4, 1), key="recuperar_dias", visible=has_fiel),
    ]

    button_column_low = [
        sg.Button("Procesar ", disabled=True, key="crear_facturas", border_width=0),
        sg.Push(),
        sg.Checkbox("Ver Detallado", default=False, key="detallado"),
        sg.Button(image_data=ABOUT_ICON, key="about", border_width=0, button_color=BUTTON_COLOR),
    ]

    # ----- Full layout -----
    return [
        button_column,
        [sg.HSeparator()],
        c_second,
        [sg.HSeparator()],
        button_column_third,
        [sg.Multiline(expand_x=True, expand_y=True, key="console", write_only=True, autoscroll=False, reroute_stdout=True)],
        button_column_low
    ]


class ActionButtonManager:
    def __init__(self, button):
        self._name = ""
        self._items = []
        self.button = button

    def set_items(self, name, items):
        self._name = name
        self._items = items
        self.style_button()

    def clear(self):
        name = self._name
        items = self._items
        self._name = ""
        self._items = []
        self.style_button()
        return name, items

    def style_button(self):
        self.button.update(
            f"Procesar {len(self._items)} {self._name.capitalize()}" if self._items else f"Procesar {self._name.capitalize()}",
            disabled=len(self._items) == 0
        )
