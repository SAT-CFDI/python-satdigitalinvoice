from datetime import date, datetime

import PySimpleGUI as sg
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

from .log_tools import *

FORMA_PAGO = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_FormaPago']
TEXT_PADDING = ((5, 0), 3)

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

PDF_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAA+0lEQVR4nN3VPUrEQBQA4E89gCBio7WI" \
           "+INbeAbxAoI3ESzEysoFd21tbe28QixE7a2t7dxGRwKvWCTrTpJNoQ9ek5k3X8hM5vEfo4cXfCFVZBkbbYDnCQunMeAM" \
           "/abAZyaQmiKpBpACmesSSHWRacA8Tiue92cF7GIN57j4kduzAB4DqfXdc4ACQ3xk7FEjYBk7GHQFrOMQl10BJ3GC7roC3mL8vivgNsYXsYmlyKIt8IojLOAYV1jFQWz6sA1QxOnZwv" \
           "7YFf6OG1xj1AYYRH9YwVPGT5jqXtejeMuHzMXL2tYNJ/2SZe3U6MXESS0zVWQ5t6zZywH+VnwDCQv1frFQIlYAAAAASUVORK5CYII="

ABOUT_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABP0lEQVR4nOWVTU7DMBCFvxuwKmrX0G4o5QLtQboDFXEbwrLkGNDucwB" \
             "+VvQObS5ApCxAIz1LCNmOG68QTxopst882y/jMfwHnAIroAQ2ilJjgxzhkYRa4AvYA6" \
             "+KvcZacYx7FBZADXwC98DUw7GxAmjEXRwjbkkfwHkCfyyu5cy7yCPtxhJOUnckruUcgGGMWMqWs8D8UhE6iZ3iMVYtrTwPoVKEUEjDW123qowL" \
             "+uNSGjche6z8YlhGLHI4hGzaAi8dyVWHReiePPsmNprMXeAdeOprUZWwQB2yaKUfNM1Y4Eoa17EyLTIWeIiVqbOp0aXx4U7hw0S565RWsevRKnYpreJ3sxsniE8kntTsHObaTaN" \
             "/MvNwZvK8ETdZ3GGocnMPjom8KeofD846xZYYBuotJmQ31MK+bSzryfwb+AbymF7gpXVM1QAAAABJRU5ErkJggg=="

REFRESH_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABGUlEQVR4nO3VzSqFURTG8Z8JYmRiJN9yDQYiKbdhYqDO9OQWyMSQDGRISoYMlHIJJEWZ" \
               "+v4oysTRrqU4nePdZej91+ptt3frWWu31/NS8kdaMINNXOANLzjFGia/ne3CdHyzGMUxarjBNpawgt0QSnsHGA6xWp1oU8bxhGvMorXBmQ5UQugO1VyBITziBD0ZxQziCh+5Aoe4z0y+ELEeyQsF0r2" \
               "/Y14etQZR2EE32jIFSv4Z7fFAfuVr3Osjh0o88ZFcgS0sRhTRF9OffEmOQBr7S/RnJO/FWUz" \
               "/QK5ANQzsOVrvbHA2DeMcbvGAsYxiflhuMr39WCfH3AurXsZOFJD2joruXcFPYwKr4a6po1ecYwNTuYlLNOMTqXpPNQBv/ywAAAAASUVORK5CYII="

BUTTON_COLOR = (sg.theme_background_color(), sg.theme_background_color())


def make_layout(has_fiel):
    # LAYOUT
    button_column = [
        sg.Button(image_data=FOLDER_ICON, key="ver_carpeta", border_width=0, button_color=BUTTON_COLOR),
        sg.Text("Año-Mes:", pad=TEXT_PADDING),
        sg.Input(date.today().strftime('%Y-%m'), size=(11, 1), key="periodo"),

        sg.Push(),
        sg.Button("Procesar ", disabled=True, key="crear_facturas", border_width=0),
        sg.VerticalSeparator(),
        sg.Text("Serie:", pad=TEXT_PADDING),
        sg.Text("", key="serie", pad=TEXT_PADDING, text_color="black"),
        sg.Text("Folio:", pad=TEXT_PADDING),
        sg.Input("", key="folio", size=(10, 1), enable_events=True),
    ]

    # ----- Full layout -----
    return [
        button_column,
        [
            sg.TabGroup(
                [[
                    sg.Tab(
                        ' Consola   ',
                        [
                            [sg.Multiline(expand_x=True, expand_y=True, key="console", write_only=True, autoscroll=False, reroute_stdout=True)]
                        ],
                        key='console_tab',
                    ),
                    sg.Tab(
                        ' Facturas  ',
                        [
                            [
                                sg.Button("Refrescar", key="refresh_facturas", border_width=0,),
                                sg.Text("", pad=TEXT_PADDING, key="preparar_facturas_text"),
                            ],
                            [
                            sg.Table(
                                values=[],
                                headings=[
                                    '#',
                                    'EReg',
                                    'Receptor Razon Social',
                                    'Recep. Rfc',
                                    "Tipo",
                                    "Subtotal",
                                    "Total"
                                ],
                                key="facturas_table",
                                expand_x=True,
                                expand_y=True,
                                select_mode=sg.TABLE_SELECT_MODE_EXTENDED,
                                enable_events=True,
                                text_color="black",
                                background_color="white",
                            )
                        ]],
                        key='facturas_tab',
                    ),
                    sg.Tab(
                        ' Clientes   ',
                        [
                            [
                                sg.Button("Refrescar", key="refresh_clientes", border_width=0, ),
                            ],
                            [
                                sg.Table(
                                    values=[],
                                    headings=[
                                        "#",
                                        "Razon Social",
                                        "Rfc",
                                        "Reg",
                                        "CP",
                                        "Facturas",
                                    ],
                                    key="clientes_table",
                                    expand_x=True,
                                    expand_y=True,
                                    select_mode=sg.TABLE_SELECT_MODE_EXTENDED,
                                    enable_events=True,
                                    text_color="black",
                                    background_color="white",
                                    def_col_width=10,
                                )
                            ]],
                        key='clients_tab',
                    ),
                    sg.Tab(
                        ' Emitidas  ',
                        [
                            [
                                sg.Button("Pendientes", key="facturas_pendientes", border_width=0),
                                sg.Button("Todas", key="facturas_emitidas", border_width=0),
                                sg.Text("", pad=TEXT_PADDING, key="emitidas_text"),
                                sg.Push(),
                                sg.Button(image_data=EXCEL_ICON, key="ver_excel", border_width=0, button_color=BUTTON_COLOR),
                                sg.Button(image_data=HTML_ICON, key="ver_html", border_width=0, button_color=BUTTON_COLOR),
                            ],
                            [
                                sg.Column(
                                    [
                                        [
                                            sg.Text("                                            ", key="factura_seleccionada", border_width=0),
                                        ],
                                        [
                                            sg.Text("", pad=(0, 3), border_width=0),
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
                                            sg.CalendarButton("FechaPago:", format='%Y-%m-%d', title="FechaPago", no_titlebar=False, target="fecha_pago", pad=TEXT_PADDING,
                                                              border_width=0,
                                                              key="fecha_pago_select", visible=False),
                                            sg.Input(datetime.now().strftime('%Y-%m-%d'), size=(12, 1), key="fecha_pago", visible=False, border_width=0),
                                            sg.Text("FormaPago:", pad=TEXT_PADDING, visible=False, key="forma_pago_text", border_width=0),
                                            sg.Combo([Code(k, v) for k, v in FORMA_PAGO.items()], default_value=Code("03", FORMA_PAGO["03"]), key="forma_pago", size=(34, 1),
                                                     visible=False),
                                        ],
                                        [
                                            sg.Button("Comprobante Pago", key="prepare_pago", border_width=0, visible=False),
                                            sg.Text("       ImpPagado:", pad=TEXT_PADDING, visible=False, key="imp_pagado_text", border_width=0),
                                            sg.Input("", size=(12, 1), key="importe_pago", visible=False, border_width=0),
                                        ]
                                    ],
                                    pad=0,
                                )
                            ],
                            [
                                sg.Table(
                                    values=[],
                                    headings=[
                                        '#',
                                        'Receptor Razon Social',
                                        'Recep. Rfc',
                                        'Factura',
                                        "Fecha",
                                        "Total",
                                        "Pagada",
                                        "Tipo",
                                        "Folio Fiscal",
                                    ],
                                    key="emitidas_table",
                                    expand_x=True,
                                    expand_y=True,
                                    select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                                    enable_events=True,
                                    text_color="black",
                                    background_color="white",
                                )
                            ]],
                        key='emitidas_tab',

                    ),
                    sg.Tab(
                        ' Correos   ',
                        [
                            [
                                sg.Button("Refrescar", key="refresh_correos", border_width=0, ),
                            ],
                            [
                                sg.Table(
                                    values=[],
                                    headings=[
                                        '#',
                                        'Receptor Razon Social',
                                        'Recep. Rfc',
                                        'Facturas',
                                        'Pendientes Emitidas Meses Anteriores'
                                    ],
                                    key="correos_table",
                                    expand_x=True,
                                    expand_y=True,
                                    select_mode=sg.TABLE_SELECT_MODE_EXTENDED,
                                    enable_events=True,
                                    text_color="black",
                                    background_color="white",
                                    def_col_width=10,
                                )
                            ]],
                        key='correos_tab',
                    ),
                    sg.Tab(
                        ' Ajustes   ',
                        [
                            [
                                sg.Button("Refrescar", key="refresh_ajustes", border_width=0, ),
                            ],
                            [
                                sg.Table(
                                    values=[],
                                    headings=[
                                        "#",
                                        "Receptor Razon Social",
                                        "Recep. Rfc",
                                        "Actual",
                                        "Nuevo",
                                        "Ajuste %",
                                        "Periodo",
                                        "Ajuste Periodo",
                                        "Ajuste Efectivo"
                                    ],
                                    key="ajustes_table",
                                    expand_x=True,
                                    expand_y=True,
                                    right_click_selects=True,
                                    select_mode=sg.TABLE_SELECT_MODE_EXTENDED,
                                    enable_events=True,
                                    text_color="black",
                                    background_color="white",
                                    def_col_width=10,
                                )
                            ]],
                        key='ajustes_tab'
                    ),
                    sg.Tab(
                        ' Recuperar ',
                        [
                            [
                                sg.Button("SAT Status", key="sat_status_todas", border_width=0, visible=has_fiel),
                                sg.Text("Recuperar:", pad=TEXT_PADDING, visible=has_fiel),
                                sg.Button("Emitidas ", key="recuperar_emitidas", border_width=0, visible=has_fiel),
                                sg.Button("Recibidas", key="recuperar_recibidas", border_width=0, visible=has_fiel),
                                sg.Text("Dias:", pad=TEXT_PADDING, visible=has_fiel),
                                sg.Input("40", size=(4, 1), key="recuperar_dias", visible=has_fiel),
                                sg.Push(),
                                sg.Button(image_data=ABOUT_ICON, key="about", border_width=0, button_color=BUTTON_COLOR),
                            ]
                        ],
                        key='recuperar_tab',
                        visible=has_fiel
                    ),
                ]],
                expand_x=True,
                expand_y=True,
                enable_events=True,
                key="main_tab_group",
            )
        ]
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
