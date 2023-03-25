import logging

import yaml
from satcfdi import Code, CFDI


class LogAdapter(logging.LoggerAdapter):
    def info_yaml(self, data):
        self.info(
            yaml.safe_dump(data, allow_unicode=True, width=1280, sort_keys=False)
        )


logger = LogAdapter(logging.getLogger())


class LogHandler(logging.StreamHandler):
    def __init__(self, console):
        super().__init__()
        self.buffer = ""
        self.console = console

    def emit(self, record):
        msg = self.format(record)
        self.buffer += msg + '\n'
        self.console.update(value=self.buffer)

    def clear(self):
        self.buffer = ""
        self.console.update(value="")


def log_cfdi(cfdi: CFDI, detailed=True):
    cfdi_copy = cfdi.copy()
    del cfdi_copy["Certificado"]
    del cfdi_copy["Sello"]

    if not detailed:
        del cfdi_copy["Serie"]
        del cfdi_copy["NoCertificado"]
        cfdi_copy.pop("Emisor")
        cfdi_copy["Receptor"] = Code(cfdi_copy['Receptor']['Rfc'], cfdi_copy['Receptor']['Nombre'])
        cfdi_copy["Conceptos"] = [x['Descripcion'] for x in cfdi_copy["Conceptos"]]  # f"<< {len(cfdi_copy['Conceptos'])} >>"
        cfdi_copy.pop("Impuestos", None)
        cfdi_copy.pop("Fecha")
        cfdi_copy.pop("LugarExpedicion")
        cfdi_copy.pop("Version")
        cfdi_copy.pop("TipoDeComprobante")
        if cfdi_copy.get("Exportacion") == "01":
            del cfdi_copy["Exportacion"]
        if cfdi_copy.get("FormaPago") == "99":
            del cfdi_copy["FormaPago"]
        if cfdi_copy.get("Moneda") in ("MXN", "XXX"):
            del cfdi_copy["Moneda"]

        if complemento := cfdi_copy.get("Complemento"):
            if pagos := complemento.get("Pagos"):
                def clean_doc(d):
                    d = d.copy()
                    d.pop("ImpuestosDR")
                    if d.get("MonedaDR") in ("MXN", "XXX"):
                        del d["MonedaDR"]
                        d.pop("EquivalenciaDR")
                    return d

                def clean_pago(p):
                    p = p.copy()
                    p.pop("ImpuestosP")
                    p["DoctoRelacionado"] = [clean_doc(x) for x in p["DoctoRelacionado"]]
                    if p.get("MonedaP") in ("MXN", "XXX"):
                        del p["MonedaP"]
                        p.pop("TipoCambioP")
                    return p

                pagos_copy = pagos.copy()
                pagos_copy["Pago"] = [clean_pago(x) for x in pagos_copy["Pago"]]
                cfdi_copy["Complemento"] = {
                    "Pagos": pagos_copy
                }

    logger.info_yaml(cfdi_copy)
