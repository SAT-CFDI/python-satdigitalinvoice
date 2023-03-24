from datetime import date, datetime

import PySimpleGUI as sg
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS
from satdigitalinvoice.gui_functions import mf_pago_fmt

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

CONFIG_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAABPElEQVR4nOWVvWoCQRSFP5NCSJHOdGkECaa3s" \
              "/MtUu6CYOcTaGMZU2efwNYtrKwkWPgK9nmAEC38IRMGTmCZrIMru6B44MLOmXPP7N6ZvQPXgiowdcJyueEFMMBMYcTlhjfgG7hR2OfhqWYB0AEqQBnoA1/APKGZi" \
              "+tLU1GOzfXiEVirBDvgE9gA70A9oauL20izU85aHgcxAlZACxgAH0DDo29IM1DOSh6paAI/QJQyVwJCIFaE4lxE8rBe//AALIA90HbMY5VgqTDikou0lbuQVyrugIkMnsSFGttN/ENHnJ1DWqNc6+FFV" \
              "+J7jWO9tYul5pDWKJc8FxhnXSBriQKNa8eUqPBNbh5xTMeK4JRjWviP5msVkdMqnsVts7aKtGbX8zS7XtZmdwhDff5tol2/ckkXTrXoK/N88Qvnr38CSEQRlwAAAABJRU5ErkJggg=="

EDIT_ICON = "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAACXBIWXMAAAsTAAALEwEAmpwYAAAA10lEQVR4nO3UPUpDQRSG4cfCQgn" \
            "+LSPLSCcEC1u3EXdgEXdg3EC2IXYS0N4itZWWGkGvDHyBkE45Npq3usyB95tz5s6w4ZfZwwQveMIFtqvkB5jhDZe4xmdCyuQdxivrk3RSIl/gAe84Ta118oytCvkQPdwmZJxxXVXJl/TSSZd6O/hvs4+7yE" \
            "/Wasd4xT2ONvIl/3gsuys3dLRWGyZ0ll/2RwwiX2SnZ5XyxnkerD5uEjKqkjemmOe7H3FXJW885rGaR9xVyg/xkZBpxjXIwZewU7VTf4ovf6VSMafchm4AAAAASUVORK5CYII="

BUTTON_COLOR = (sg.theme_background_color(), sg.theme_background_color())


class MyTable(sg.Table):
    def __init__(self, key, headings, row_fn):
        super().__init__(
            values=[],
            key=key,
            headings=headings,
            expand_x=True,
            expand_y=True,
            select_mode=sg.TABLE_SELECT_MODE_EXTENDED,
            enable_events=True,
            text_color="black",
            background_color="white",
            # headings=HEADINGS,
            # values=[],
            # auto_size_columns=False,
            # col_widths=COL_WIDTHS,
            # justification="center",
            # num_rows=20,
            alternating_row_color="grey95", #"aliceblue",
            # row_height=ROW_HEIGHT,
            # header_text_color="white",
            # header_background_color="darkblue",
            # font=FONT,
            # bind_return_key=True,
            tooltip="Doble click para ver factura",
            # right_click_menu=RIGHT_CLICK_MENU
            metadata=[]
        )
        self.row_fn = row_fn

    def selected_items(self):
        return [self.metadata[i] for i in self.SelectedRows]

    def select_all(self):
        self.update(
            select_rows=list(range(len(self.metadata)))
        )

    def update(self, values=None, **kwargs):
        super().update(
            values=[
                self.row_fn(i, item)
                for i, item in enumerate(values, start=1)
            ],
            **kwargs
        )
        self.metadata = values


def make_layout(has_fiel, local_db):
    # LAYOUT
    button_column = [
        sg.Button(image_data=CONFIG_ICON, key="ver_config", border_width=0, button_color=BUTTON_COLOR),
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
                        'Clientes'.center(13),
                        [
                            [
                                sg.Button("Refrescar", key="refresh_clientes", border_width=0),
                                sg.Push(),
                                sg.Button(image_data=EDIT_ICON, key="editar_clientes", border_width=0, button_color=BUTTON_COLOR),
                            ],
                            [
                                MyTable(
                                    key="clientes_table",
                                    headings=[
                                        "#",
                                        "Razon Social",
                                        "Rfc",
                                        "Reg",
                                        "CP"
                                    ],
                                    row_fn=lambda i, r: [
                                        i,
                                        r["RazonSocial"],
                                        r["Rfc"],
                                        r["RegimenFiscal"].code,
                                        r["CodigoPostal"]
                                    ]
                                )
                            ]],
                        key='clients_tab',
                    ),
                    sg.Tab(
                        'Facturas'.center(13),
                        [
                            [
                                sg.Button("Refrescar", key="refresh_facturas", border_width=0, ),
                                sg.Text("", pad=TEXT_PADDING, key="preparar_facturas_text"),
                                sg.Push(),
                                sg.Button(image_data=EDIT_ICON, key="editar_facturas", border_width=0, button_color=BUTTON_COLOR),
                            ],
                            [
                                MyTable(
                                    key="facturas_table",
                                    headings=[
                                        '#',
                                        'EReg',
                                        'Receptor Razon Social',
                                        'Recep. Rfc',
                                        "Tipo",
                                        "Subtotal",
                                        "Total"
                                    ],
                                    row_fn=lambda i, r: [
                                        i,
                                        r['Emisor']['RegimenFiscal'].code,
                                        r['Receptor']['Nombre'],
                                        r['Receptor']['Rfc'],
                                        mf_pago_fmt(r),
                                        r['SubTotal'],
                                        r['Total']
                                    ]
                                )
                            ]],
                        key='facturas_tab',
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
                                MyTable(
                                    key="emitidas_table",
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
                                    row_fn=lambda i, r: [
                                        i,
                                        r['Receptor'].get('Nombre', ''),
                                        r['Receptor']['Rfc'],
                                        r.name,
                                        r["Fecha"].strftime("%Y-%m-%d"),
                                        r["Total"],
                                        local_db.liquidated_state(r),
                                        mf_pago_fmt(r)
                                    ]
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
                                MyTable(
                                    key="correos_table",
                                    headings=[
                                        '#',
                                        'Receptor Razon Social',
                                        'Recep. Rfc',
                                        'Facturas',
                                        'Pendientes Emitidas Meses Anteriores'
                                    ],
                                    row_fn=lambda i, r: [
                                        i,
                                        r[0]["RazonSocial"][0:36],
                                        r[0]["Rfc"],
                                        ",".join(n.name for n in r[1]),
                                        ",".join(n.name for n in r[2])
                                    ]
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
                                MyTable(
                                    key="ajustes_table",
                                    headings=[
                                        "#",
                                        "Receptor Razon Social",
                                        "Recep. Rfc",
                                        "Actual",
                                        "Nuevo",
                                        "Ajuste %",
                                        "Periodo",
                                        "Meses",
                                        "Ajuste Efectivo"
                                    ],
                                    row_fn=lambda i, r: [
                                        i,
                                        r["receptor"]["RazonSocial"],
                                        r["receptor"]["Rfc"],
                                        r["valor_unitario"],
                                        r["valor_unitario_nuevo"],
                                        r["ajuste_porcentaje"],
                                        r["periodo"],
                                        r["meses"],
                                        r["efectivo_periodo_desc"]
                                    ]
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
