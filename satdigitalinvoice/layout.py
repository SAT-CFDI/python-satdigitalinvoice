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

PREVIEW_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABKElEQVR4nO2VMU8CQRCFP6WAQksqOxJ/A6WJUFFprJSEilARWgsa" \
               "/4IVLYUNFZ0WVECwNxpCIDQYfwEVGj0zycNcCOTulqMxvGQze2/eztub3O3Cf0QJ6IQYD8CRi8Ed4AUUn0rTczFZGoTRfLmYRDG4Aj6BAXC8C4M80NC8H/ZNohh4K6Mel0FGu" \
               "/cPT2tjMViHvUEg9i0KxBmQjeszPVSxCnCrmBW/lUECqAKzDX/yTPmEi0EaeFauq0JDzU+BG809HX7pKAYnwAiYA9fi7qVr+jZgKEo30rqNBh2dlAe65Yx7BJLStX2teQFa4i3/JN7WBV6Z5+JrwA/wKu4S" \
               "+FYhixdADniTzvSRUQDeVXSsNiwUJ+ItbzpnpICy2vAhA4v2bLzl//ALOtSCJzC7jH4AAAAASUVORK5CYII="

SEARCH_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABM0lEQVR4nOXTuytAYRzG8Y8RJTPJ5jJIitwGoxiZGSTZDAaDTQaJhYWBf0A" \
              "WRDHjD7BIMrkUg2wol079lEGc1yXJU2c4b8/5Pu/vfZ/Df1MjJrGKLSyjHyVfBZdjE0+4wwH2cB5rVxj8LLwmQNcYeWO3TdiOoJlUeDGOcIbqd3wFmI2QgZSAcTyiPYc3C9nBZcq" \
              "dnGAjYUPNMUVfHnNlmIcSArIpLrCUx9wSAZ3StB8V/lD1EdCTGJBVeCVvg+4wlQAvxT0m8n6wERUtyukfjakb8ga04QELOby1uMGaxFbsxq4W49jeUke05xRlKfD5gO/GJBlkGr3" \
              "ownA0JvsZD1H1Gfh8vLdiHbex/vIcYwyFX4G/VnbhdRFYIVEZbO7VmRekAn4Nnqn7nWP5NnX9JNyf1DM+Yku7BVpvYgAAAABJRU5ErkJggg=="


BUTTON_COLOR = (sg.theme_background_color(), sg.theme_background_color())


def make_layout(has_fiel):
    # LAYOUT
    button_column = [
        sg.Text("Periodo:", pad=TEXT_PADDING),
        sg.Input(date.today().strftime('%Y-%m'), size=(11, 1), key="periodo"),
        sg.Button(image_data=FOLDER_ICON, key="ver_carpeta", border_width=0, button_color=BUTTON_COLOR),
        sg.Button(image_data=EXCEL_ICON, key="ver_excel", border_width=0, button_color=BUTTON_COLOR),
        sg.Button(image_data=HTML_ICON, key="ver_html", border_width=0, button_color=BUTTON_COLOR),

        sg.Push(),
        sg.Text("Factura:", pad=TEXT_PADDING),
        sg.Text("", key="serie", pad=TEXT_PADDING, text_color="black"),
        sg.Input("", key="folio", size=(8, 1), enable_events=True),
        sg.Button("".center(22), disabled=True, key="crear_facturas", border_width=0, button_color=sg.theme_background_color()),
    ]

    # ----- Full layout -----
    return [
        button_column,
        [
            sg.TabGroup(
                [[
                    sg.Tab(
                        'Consola'.center(13),
                        [
                            [
                                sg.Push(),
                                sg.Button(image_data=ABOUT_ICON, key="about", border_width=0, button_color=BUTTON_COLOR),
                            ],
                            [sg.Multiline(
                                expand_x=True,
                                expand_y=True,
                                key="console",
                                write_only=True,
                                autoscroll=True,
                                reroute_stdout=True
                            )]
                        ],
                        key='console_tab',
                    ),
                    sg.Tab(
                        'Facturas'.center(13),
                        [
                            [
                                sg.Button("Refrescar", key="refresh_facturas", border_width=0, ),
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
                        'Clientes'.center(13),
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
                        'Emitidas'.center(13),
                        [
                            [
                                sg.Button("Pendientes", key="facturas_pendientes", border_width=0),
                                sg.Button("Todas", key="facturas_emitidas", border_width=0),
                                sg.Button(image_data=SEARCH_ICON, key="emitidas_search_enter", border_width=0, button_color=BUTTON_COLOR),
                                sg.Input("", size=(20, 1), key="emitidas_search", border_width=0),
                                sg.Text("", pad=TEXT_PADDING, key="emitidas_text"),
                            ],
                            [
                                sg.Column([[
                                    sg.Button("".ljust(10), key="status_sat", border_width=0, button_color=sg.theme_background_color()),
                                    sg.Button("".ljust(10), key="email_notificada", border_width=0, button_color=sg.theme_background_color()),
                                    sg.Button("".ljust(10), key="pendiente_pago", border_width=0, button_color=sg.theme_background_color()),
                                ]]),
                                sg.VSeparator(),
                                sg.Column([[
                                    sg.CalendarButton("FechaPago:", format='%Y-%m-%d', title="FechaPago", no_titlebar=False, target="fecha_pago", pad=TEXT_PADDING,
                                                      border_width=0,
                                                      key="fecha_pago_select"),
                                    sg.Input(datetime.now().strftime('%Y-%m-%d'), size=(12, 1), key="fecha_pago", border_width=0),
                                    sg.Combo([Code(k, v) for k, v in FORMA_PAGO.items()], default_value=Code("03", FORMA_PAGO["03"]), key="forma_pago", size=(28, 1)),
                                    sg.Text("ImpPagado:", pad=TEXT_PADDING, key="imp_pagado_text", border_width=0),
                                    sg.Input("", size=(12, 1), key="importe_pago", border_width=0),
                                    sg.Button("Comprobante Pago", key="prepare_pago", border_width=0),
                                    sg.Button(image_data=PREVIEW_ICON, key="ver_html_pago", border_width=0, button_color=BUTTON_COLOR),
                                ]], visible=False, key="ppd_action_items"),
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
                        'Correos'.center(13),
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
                        'Ajustes'.center(13),
                        [
                            [
                                sg.Button("Refrescar", key="refresh_ajustes", border_width=0, ),
                                sg.Text("", pad=TEXT_PADDING, key="preparar_ajustes_text"),
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
                        'Recuperar'.center(13),
                        [
                            [
                                sg.Button("SAT Status", key="sat_status_todas", border_width=0),
                                sg.Text("Recuperar:", pad=TEXT_PADDING),
                                sg.Button("Emitidas ", key="recuperar_emitidas", border_width=0),
                                sg.Button("Recibidas", key="recuperar_recibidas", border_width=0),
                                sg.Text("Dias:", pad=TEXT_PADDING),
                                sg.Input("40", size=(4, 1), key="recuperar_dias"),
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
        self.name = ""
        self.items = []
        self.button = button

    def set_items(self, name, items):
        self.name = name
        self.items = items
        self.style_button()

    def clear(self):
        self.name = ""
        self.items = []
        self.style_button()

    def text(self):
        if self.items:
            return f"Procesar {len(self.items)} {self.name.capitalize()}"
        else:
            return ""

    def style_button(self):
        self.button.update(
            self.text().center(22),
            disabled=not self.items,
            button_color=sg.theme_button_color() if self.items else sg.theme_background_color()
        )
