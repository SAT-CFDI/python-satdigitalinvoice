

{{ receptor.RazonSocial }}<br>
{{ receptor.Rfc }}<br>

<br>
<div style="text-align: right">Nation</div>
<div style="text-align: right">{{ fecha_hoy }}</div>
<div style="text-align: right">{{ emisor.CodigoPostal }}</div>
<br>
<br><br><br><br><br><br>

HELLO THERE
<br><br><br>


{{ ajuste_periodo }}
WILL BE {{ ajuste_porcentaje }}
CONCEPT DESCRIPTION {{ concepto.Descripcion }}  
NEW {{ valor_unitario_nuevo }} 

{% if concepto.Impuestos.Retenciones is defined and concepto.Impuestos.Retenciones %}
HAS RETENTIONS
{% endif %}
EFECTIVE {{ ajuste_efectivo_al }}.

<br><br><br><br><br><br>

<br><br><br><br><br><br>

SINCERELY

<br>
<br>
<br>"<strong><em>NOTIFIER</em></strong>"
<br>{{ emisor.RazonSocial }}
<br>{{ emisor.Rfc }}
{% for e in emisor.Email %}
<br>{{ e }}
{% endfor %}
{% if emisor.Celular is defined %}
<br>Cel. {{ emisor.Celular }}
{% endif %}
