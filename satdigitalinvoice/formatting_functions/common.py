from babel.dates import format_date
from num2words import num2words

LANG = 'es_CO'


def pesos(amount):
    decimal_part = "{:.2f}".format(amount).split(".")[1]
    integer_part = num2words(int(amount), lang=LANG, to='currency').upper()

    return "${0:,.2f} (SON: {1} {2}/100M.N.)".format(amount, integer_part, decimal_part)


def num_letras(number):
    return num2words(number, lang=LANG).upper()


def numero(k):
    return str(k) + ' (' + num_letras(k) + ')'


def porcentaje(k):
    return str(k) + '% (' + num_letras(k) + ' POR CIENTO)'


def fecha(date):
    return format_date(date, locale='es_MX', format="d 'de' MMMM 'del' y").upper()


def fecha_mes(date):
    return format_date(date, locale='es_MX', format="'Mes de' MMMM 'del' y").upper()
