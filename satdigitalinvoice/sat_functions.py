from decimal import Decimal

from satcfdi.create.cfd.catalogos import Impuesto, TipoFactor, RegimenFiscal
from satcfdi.models import DatePeriod, RFC, RFCType
from satcfdi.utils import iterate

ISR_MENSUAL_2023 = [  # limite, cuota_fija, porcentaje
    (Decimal('375975.62'), Decimal("117912.32"), Decimal("0.3500")),
    (Decimal('125325.21'), Decimal("32691.18"), Decimal("0.3400")),
    (Decimal('93993.91'), Decimal("22665.17"), Decimal("0.3200")),
    (Decimal('49233.01'), Decimal("9236.89"), Decimal("0.3000")),
    (Decimal('31236.50'), Decimal("5004.12"), Decimal("0.2352")),
    (Decimal('15487.72'), Decimal("1640.18"), Decimal("0.2136")),
    (Decimal('12935.83'), Decimal("1182.88"), Decimal("0.1792")),
    (Decimal('11128.02'), Decimal("893.63"), Decimal("0.1600")),
    (Decimal('6332.06'), Decimal("371.83"), Decimal("0.1088")),
    (Decimal('746.05'), Decimal("14.32"), Decimal("0.0640")),
    (Decimal("0.00"), Decimal("0.00"), Decimal("0.0192")),
]

ISR_ANUAL_2023 = [  # limite, cuota_fija, porcentaje
    (Decimal('4511707.38'), Decimal("1414947.85"), Decimal("0.3500")),
    (Decimal('1503902.47'), Decimal("392294.17"), Decimal("0.3400")),
    (Decimal('1127926.85'), Decimal("271981.99"), Decimal("0.3200")),
    (Decimal('590796.00'), Decimal("110842.74"), Decimal("0.3000")),
    (Decimal('374837.89'), Decimal("60049.40"), Decimal("0.2352")),
    (Decimal('185852.58'), Decimal("19682.13"), Decimal("0.2136")),
    (Decimal('155229.81'), Decimal("14194.54"), Decimal("0.1792")),
    (Decimal('133536.08'), Decimal("10723.55"), Decimal("0.1600")),
    (Decimal('75984.56'), Decimal("4461.94"), Decimal("0.1088")),
    (Decimal('8952.50'), Decimal("171.88"), Decimal("0.0640")),
    (Decimal("0.00"), Decimal("0.00"), Decimal("0.0192")),
]

ISR_MENSUAL_RESICO_2023 = [
    (Decimal("208333.34"), None, Decimal("0.0250")),
    (Decimal("83333.34"), None, Decimal("0.0200")),
    (Decimal("50000.01"), None, Decimal("0.0150")),
    (Decimal("25000.01"), None, Decimal("0.0110")),
    (Decimal("0.00"), None, Decimal("0.0100")),
]


def isr_mensual(dp: DatePeriod, ingreso):
    if dp.month is None:
        isr_table = ISR_ANUAL_2023
    else:
        isr_table = ISR_MENSUAL_2023

    for (limite, cuota_fija, porcentaje) in isr_table:
        if ingreso >= limite:
            return round((ingreso - limite) * porcentaje + cuota_fija)
    return Decimal("0.00")


def sat_retenciones(concepto, emisor, receptor):
    if 'Retenciones' in concepto['Impuestos']:
        return

    emisor_rfc = RFC(emisor['Rfc'])
    receptor_rfc = RFC(receptor['Rfc'])

    if emisor_rfc.type == RFCType.FISICA and receptor_rfc.type == RFCType.MORAL:
        ret_isr = {
            'Impuesto': Impuesto.ISR,
            'TipoFactor': TipoFactor.TASA,
            'TasaOCuota': Decimal('0.100000') if emisor['RegimenFiscal'] != RegimenFiscal.REGIMEN_SIMPLIFICADO_DE_CONFIANZA else Decimal('0.012500')
        }

        if receptor['RegimenFiscal'] == '603':  # Personas morales con fines no lucrativos
            concepto['Impuestos']['Retenciones'] = ret_isr  # solo se retiene ISR
        else:
            traslado = next(i for i in iterate(concepto['Impuestos']['Traslados']) if i['Impuesto'] == Impuesto.IVA)
            assert traslado is not None
            assert traslado['TipoFactor'] == TipoFactor.TASA

            concepto['Impuestos']['Retenciones'] = [
                ret_isr,
                {
                    'Impuesto': Impuesto.IVA,
                    'TipoFactor': TipoFactor.TASA,
                    'TasaOCuota': round(traslado['TasaOCuota'] * 2 / 3, 6)
                }
            ]
