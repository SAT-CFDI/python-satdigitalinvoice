from datetime import date

import PySimpleGUI as sg
from dateutil.relativedelta import relativedelta
# noinspection PyUnresolvedReferences
from satcfdi.transform.catalog import CATALOGS

from .log_tools import *

FORMA_PAGO = CATALOGS['{http://www.sat.gob.mx/sitio_internet/cfd/catalogos}c_FormaPago']
TEXT_PADDING = ((5, 0), 3)
RTEXT_PADDING = ((0, 0), 3)


def make_layout(has_fiel):
    # LAYOUT
    button_column = [
        sg.Button("Preparar Facturas", key="prepare_facturas", border_width=0),
        sg.Text("Año-Mes:", pad=TEXT_PADDING),
        sg.Input(date.today().strftime('%Y-%m'), size=(8, 1), key="periodo", change_submits=True),
        sg.Text("De La:", pad=TEXT_PADDING),
        sg.Input("1", key="inicio", size=(4, 1), change_submits=True),
        sg.Text("Hasta:", pad=TEXT_PADDING),
        sg.Input("", key="final", size=(4, 1), change_submits=True),
        sg.Text("             ", pad=TEXT_PADDING),
        sg.Button("Exportar Excel", key="exportar_facturas", border_width=0),
        sg.Button("Ver Excel", key="ver_excel", border_width=0),
    ]

    c_second = [
        sg.Column(
            [
                [
                    sg.Button("Buscar Factura:", key="buscar_factura", border_width=0, pad=TEXT_PADDING),
                    sg.Input("", size=(40, 1), key="factura_pagar", change_submits=True),
                    sg.Button("Descarga", key="descarga", border_width=0, disabled=True),
                ],
                [
                    sg.Button("Status SAT", key="status_sat", border_width=0, disabled=True),
                    sg.Button("PUE Pagada", key="pago_pue", border_width=0, disabled=True),
                    sg.Button("PPD Ignorar", key="ignorar_ppd", border_width=0, disabled=True),
                    sg.Button("Email Notificada", key="email_notificada", border_width=0, disabled=True),
                    sg.Button(" Ver PDF ", key="ver_factura", border_width=0, disabled=True),
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
                    sg.Input("", size=(12, 1), key="fecha_pago", change_submits=True, disabled=True),
                    sg.Text("FormaPago:", pad=TEXT_PADDING),
                    sg.Combo([Code(k, v) for k, v in FORMA_PAGO.items()], default_value=Code("03", FORMA_PAGO["03"]), key="forma_pago", change_submits=True, size=(34, 1), disabled=True),
                ],
                [
                    sg.Button("Preparar Comprobante Pago", key="prepare_pago", border_width=0, disabled=True),
                ]
            ],
            pad=0
        )
    ]

    button_column_third = [
        sg.Button("Preparar Correos", key="prepare_correos", border_width=0),
        sg.Button("Facturas Pendientes", key="facturas_pendientes", border_width=0),
        sg.Checkbox("Ver Detallado", default=False, key="detallado"),
        sg.VSeparator(),
        sg.Button("Ajuste Anual", key="preparar_ajuste_anual", border_width=0),
        sg.Text("Año-Mes:", pad=TEXT_PADDING),
        sg.Input((date.today() + relativedelta(months=1)).strftime('%Y-%m'), size=(8, 1), key="anio_mes_ajuste"),
        sg.Text("Ajuste:", pad=TEXT_PADDING),
        sg.Input("", size=(6, 1), key="ajuste_porcentaje"),
        sg.Text("%", pad=RTEXT_PADDING),
        sg.VSeparator(),
        sg.Text("Recuperar:", pad=TEXT_PADDING),
        sg.Button("Emitidas", key="recuperar_emitidas", border_width=0, disabled=not has_fiel),
        sg.Button("Recibidas", key="recuperar_recibidas", border_width=0, disabled=not has_fiel),
        sg.Text("Dias:", pad=TEXT_PADDING),
        sg.Input("40", size=(4, 1), key="recuperar_dias", disabled=not has_fiel),
    ]

    button_column_low = [
        sg.Button("Validar Clientes", key="validate_clientes", border_width=0),
        sg.Button("Crear Facturas", disabled=True, key="crear_facturas", border_width=0),
        sg.Button("Enviar Correos", disabled=True, key="enviar_correos", border_width=0),
        sg.Push(),
        sg.Button("Acerca De", key="about", border_width=0),
    ]

    # ----- Full layout -----
    return [
        button_column,
        [sg.HSeparator()],
        c_second,
        [sg.HSeparator()],
        button_column_third,
        [sg.Multiline(expand_x=True, expand_y=True, key="console", write_only=True, autoscroll=True, reroute_stdout=True)],
        button_column_low
    ]


class InvoiceButtonManager:
    def __init__(self, button, detallado):
        self._cfdis = []
        self.button = button
        self.detallado = detallado

    def set_invoices(self, invoices):
        self._cfdis = invoices
        self.style_button()

    def clear(self):
        cfdis = self._cfdis
        self._cfdis = []
        self.style_button()
        return cfdis

    def style_button(self):
        self.button.update(
            f"Crear {len(self._cfdis)} Facturas" if self._cfdis else "Crear Facturas",
            disabled=len(self._cfdis) == 0
        )


class EmailButtonManager:
    def __init__(self, button):
        self._emails = {}
        self.button = button

    def set_emails(self, emails):
        self._emails = emails

        for i, (receptor, notify_invoices, facturas_pendientes) in enumerate(emails, start=1):
            log_item(f"CORREO NUMERO: {i}")
            log_email(receptor, notify_invoices, facturas_pendientes)

        self.style_button()

    def clear(self):
        emails = self._emails
        self._emails = {}
        self.style_button()
        return emails

    def style_button(self):
        self.button.update(
            f"Enviar {len(self._emails)} Correos" if self._emails else "Enviar Correos",
            disabled=len(self._emails) == 0
        )

