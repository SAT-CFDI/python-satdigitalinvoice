from babel.dates import format_date
from dateutil import rrule
from num2words import num2words


def pesos(amount):
    amount = round(amount, 2)
    decimal_part = "{:.2f}".format(amount).split(".")[1]
    integer_part = int(amount)
    integer_part = number_to_currency(integer_part).upper()

    return "${0:,.2f} (SON: {1} {2}/100M.N.)".format(amount, integer_part, decimal_part)


def porcentaje(amount, decimals=2):
    percentage = amount * 100
    percentage = round(percentage, decimals)
    percentage_text = number_to_text(percentage).upper()

    return "{0}% ({1} POR CIENTO)".format(percentage, percentage_text)


def number_to_currency(number):
    return num2words(number, lang='es_CO', to='currency')


def number_to_text(number):
    return num2words(number, lang='es_CO')


def date_range(start, end):
    return "{0} AL {1}".format(fecha(start), fecha(end))


def fecha(date):
    return format_date(date, locale='es_MX', format="d 'de' MMMM 'del' y").upper()


def data_range_length_months(start, end):
    months = len(list(rrule.rrule(rrule.MONTHLY, dtstart=start, until=end)))
    months_text = number_to_text(months).upper()
    return "{0} ({1} MESES)".format(months, months_text)


def meses(count):
    months = count
    months_text = number_to_text(months).upper()
    return "{0} ({1} MESES)".format(months, months_text)
