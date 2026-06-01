from babel.dates import format_date, get_month_names
from num2words import num2words

LANG = 'es_CO'
LOCALE = 'es_MX'


def pesos(amount):
    decimal_part = "{:.2f}".format(amount).split(".")[1]
    integer_part = num2words(int(amount), lang=LANG, to='currency').upper()

    return "${0:,.2f} (SON: {1} {2}/100 M.N.)".format(amount, integer_part, decimal_part)


# def pesos_sinletra(amount):
#     return "${0:,.2f}".format(amount)

def num_letras(number):
    return num2words(number, lang=LANG).upper()


def numero(k):
    return str(k) + ' (' + num_letras(k) + ')'


def porcentaje(k):
    return str(k) + '% (' + num_letras(k) + ' POR CIENTO)'


def fecha(date):
    day_numero = num_letras(date.day)
    anio_numero = num_letras(date.year)
    formated_d = format_date(date, locale=LOCALE, format="d '({0}) de' MMMM 'del' yyyy '({1})'")
    return formated_d.format(day_numero, anio_numero).upper()


def fecha_mes(date):
    return format_date(date, locale=LOCALE, format="'Mes de' MMMM 'del' y").upper()


# function to get month name from number
def get_month_name(month_number):
    return get_month_names('wide', locale=LOCALE)[month_number].upper()


def delta_tiempo(duracion):
    months = duracion.years * 12 + duracion.months
    # if months == 12:
    #     return '1 (UN) AÑO'
    return numero(months) + ' MESES'
