#!/usr/bin/env python3
"""
ValQual Market Monitor - email semanal por Brevo.

Construye el email de la semana a partir de data/market.json y data/europe.json
y, si se pide, lo envía como campaña de Brevo a las listas indicadas.

Uso:
    python scripts/email_semanal.py construir   # solo genera salida/ (email y vista previa)
    python scripts/email_semanal.py prueba      # envía una prueba a EMAIL_PRUEBA
    python scripts/email_semanal.py enviar      # crea la campaña de la semana para BREVO_LISTAS

Variables de entorno (en GitHub: Settings > Secrets and variables > Actions):
    BREVO_API_KEY   (secreto) clave de la API de Brevo. Necesaria para prueba y enviar.
    BREVO_LISTAS    IDs de las listas separados por comas, p. ej. "6" o "6,3,4,5".
    EMAIL_SEMANAL   interruptor: tiene que valer "on" para enviar de verdad.
    EMAIL_PRUEBA    destinatario de la prueba (por defecto info@valqual.app).
    EMAIL_HORA_UTC  hora de envío del sábado en UTC (por defecto 15:00: 9:00 en
                    Ciudad de México, 16:00 en Madrid en invierno). Si ya ha pasado,
                    se envía en el momento.
    MONITOR_URL     dirección pública del Market Monitor.
    BREVO_LIMITE    máximo de contactos por envío (por defecto 280; el plan gratuito
                    de Brevo permite 300 emails al día entre todos los envíos).

Reglas de seguridad al enviar:
    - sin EMAIL_SEMANAL=on no se envía nada;
    - los datos de EE. UU. tienen que ser de los últimos 3 días y no de demostración;
    - una sola campaña por semana (se busca en Brevo por su nombre);
    - si las listas suman más contactos que BREVO_LIMITE, no se envía;
    - se comprueban los enlaces del email antes de crear la campaña.

Licencias: el email no reproduce valores del S&P 500 ni del VIX (series con
copyright de S&P Dow Jones Indices y Cboe en FRED); usa las lecturas y tramos.

Diseño: el mismo marco que los demás emails de ValQual en Brevo.

Solo usa la biblioteca estándar de Python.
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_EEUU = ROOT / "data" / "market.json"
DATA_EUROPA = ROOT / "data" / "europe.json"
SALIDA = ROOT / "salida"

API = "https://api.brevo.com/v3"
UA = "ValQual-MarketMonitor/1.0 (+https://valqual.app)"
REMITENTE = {"name": "ValQual", "email": "info@valqual.app"}
RESPONDER_A = "info@valqual.app"
WEB = "https://valqual.app/"
MONITOR_POR_DEFECTO = "https://valqualapp.github.io/market-monitor/"
UTM = {"utm_source": "brevo", "utm_medium": "email", "utm_campaign": "monitor_semanal"}

ASUNTO = "El mercado esta semana, sin ruido · {fecha}"
DIAS_FRESCOS = 3
LIMITE_POR_DEFECTO = 280
HORA_POR_DEFECTO = "15:00"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Bloques del resumen, en el orden del email. La tendencia de Europa no tiene
# lectura propia (se ve en el gráfico de TradingView de la página).
BLOQUES_EEUU = [("trend", "Tendencia"), ("vix", "Volatilidad"),
                ("financial", "Condiciones financieras"), ("cycle", "Ciclo económico"),
                ("inflation", "Inflación")]
BLOQUES_EUROPA = [("financial", "Condiciones financieras"), ("cycle", "Ciclo económico"),
                  ("inflation", "Inflación")]

# El VIX se describe por tramos (las mismas reglas de la página), sin su valor.
TEXTO_VIX = {
    "good": "El VIX está por debajo de 20: la volatilidad que espera el mercado está dentro de lo habitual.",
    "warn": "El VIX está entre 20 y 30: el mercado espera más volatilidad de lo habitual.",
    "bad": "El VIX está en 30 o más: el mercado descuenta una volatilidad alta.",
}

# Un recurso de valqual.app por semana: el grupo depende del contexto y, dentro
# del grupo, va rotando por número de semana. Si un enlace falla, se usa el siguiente.
PIEZAS = {
    "caidas": [
        {"url": "lab/tyranny-average.html", "tipo": "Lab", "titulo": "Lo que cuesta recuperar una caída",
         "texto": "Un experimento interactivo sobre por qué la media de las rentabilidades engaña cuando hay pérdidas."},
        {"url": "blog/disciplina-inversion.html", "tipo": "Blog", "titulo": "Reglas de cartera antes que impulsos",
         "texto": "Por qué conviene decidir las reglas antes de que llegue la próxima caída."},
        {"url": "blog/obsesion-predecir.html", "tipo": "Blog", "titulo": "La obsesión por predecir el mercado",
         "texto": "Por qué un proceso sirve más que acertar el próximo movimiento."},
    ],
    "inflacion": [
        {"url": "tools.html", "tipo": "Herramienta", "titulo": "Calculadora de inflación",
         "texto": "Calcula cuánto poder de compra pierde tu dinero con los años."},
        {"url": "blog/interes-compuesto.html", "tipo": "Blog", "titulo": "El interés compuesto y la lata de café",
         "texto": "Cómo el tiempo y la constancia trabajan a favor de quien invierte."},
    ],
    "general": [
        {"url": "lab/overfitting.html", "tipo": "Lab", "titulo": "El backtest perfecto que no funciona",
         "texto": "Un experimento sobre el sobreajuste: estrategias que solo funcionan en el pasado."},
        {"url": "lab/diversification-illusion.html", "tipo": "Lab", "titulo": "La ilusión de la diversificación",
         "texto": "Por qué tener muchos activos no siempre reparte el riesgo."},
        {"url": "blog/kahneman.html", "tipo": "Blog", "titulo": "Kahneman y los sesgos al invertir",
         "texto": "Los atajos mentales que más pesan cuando el mercado se mueve."},
        {"url": "blog/sistemas-inversores.html", "tipo": "Blog", "titulo": "Por qué invertir con un sistema",
         "texto": "Reglas claras para decidir con menos emoción."},
        {"url": "blog/etfs-inversion.html", "tipo": "Blog", "titulo": "Qué es un ETF y cómo leer su ficha",
         "texto": "Lo básico antes de comprar un fondo cotizado."},
        {"url": "perfil-inversor.html", "tipo": "Test", "titulo": "Explora tu perfil inversor",
         "texto": "12 preguntas, unos 5 minutos, para conocer tu forma de invertir."},
    ],
}

# Colores de cada etiqueta: texto, borde y fondo.
TONOS = {
    "good": ("#1d7a55", "#a8d9c3", "#ecf7f2"),
    "warn": ("#9a5a0e", "#efc796", "#fdf4e7"),
    "bad": ("#ad3a2a", "#eeb2a8", "#fcedeb"),
    "": ("#57606a", "#d0d7de", "#f6f8fa"),
}
NOMBRE_TONO = {"good": ("favorable", "favorables"), "warn": ("a vigilar", "a vigilar"),
               "bad": ("preocupante", "preocupantes")}

# Mismo marco que los demás emails de ValQual en Brevo (secuencia del Módulo 0, cupón, Ranking).
FUENTE = "Inter,Arial,Helvetica,sans-serif"
TEXTO = "#1f2328"
SUAVE = "#57606a"
PIE = "#6e7781"
DORADO = "#8a6d1f"
LINEA = "#e5e7eb"


class ErrorEnvio(Exception):
    """Error que impide enviar; el mensaje es para la persona que mira el registro."""


class BrevoError(ErrorEnvio):
    def __init__(self, estado: int, mensaje: str, cuerpo=None):
        super().__init__(mensaje)
        self.estado = estado
        self.cuerpo = cuerpo or {}


# ---------------------------------------------------------------------------
# Fechas y datos
# ---------------------------------------------------------------------------
def ahora_utc() -> datetime:
    forzada = os.environ.get("VQ_AHORA", "").strip()  # solo para pruebas
    if forzada:
        return parse_fecha(forzada)
    return datetime.now(timezone.utc)


def parse_fecha(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hora_madrid(dt: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception:  # noqa: BLE001 - sin base de datos de zonas horarias
        return dt


def fecha_larga(dt: datetime) -> str:
    d = hora_madrid(dt)
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def fecha_corta(dt: datetime) -> str:
    d = hora_madrid(dt)
    return f"{d.day} {MESES_CORTOS[d.month - 1]}"


def semana_iso(dt: datetime) -> str:
    año, semana, _ = hora_madrid(dt).isocalendar()
    return f"{año}-W{semana:02d}"


def cargar(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def es_fresco(datos: dict | None, ahora: datetime) -> bool:
    try:
        actualizado = parse_fecha(datos["meta"]["updated_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return not datos["meta"].get("demo") and timedelta(0) <= ahora - actualizado <= timedelta(days=DIAS_FRESCOS)


def europa_valida(eu: dict | None, us: dict) -> bool:
    """Europa entra si no es de demostración y es de la misma actualización que EE. UU. (±3 días)."""
    try:
        diferencia = abs(parse_fecha(eu["meta"]["updated_at"]) - parse_fecha(us["meta"]["updated_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return not eu["meta"].get("demo") and diferencia <= timedelta(days=DIAS_FRESCOS)


def filas(datos: dict | None, bloques: list[tuple[str, str]]) -> list[dict]:
    lecturas = (datos or {}).get("readings") or {}
    salida = []
    for clave, nombre in bloques:
        r = lecturas.get(clave)
        if not r or not r.get("label"):
            continue
        tono = r.get("tone") if r.get("tone") in TONOS else ""
        texto = r.get("text") or ""
        if clave == "vix":  # sin el valor del índice
            texto = TEXTO_VIX.get(tono, "Consulta el VIX en la página del Market Monitor.")
        salida.append({"clave": clave, "nombre": nombre, "tono": tono, "estado": r["label"], "texto": texto})
    return salida


def conteo(fs: list[dict]) -> str:
    partes = []
    for tono in ("good", "warn", "bad"):
        n = sum(1 for f in fs if f["tono"] == tono)
        if n:
            singular, plural = NOMBRE_TONO[tono]
            partes.append(f"{n} {singular if n == 1 else plural}")
    if not partes:
        return ""
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def tono_de(fs: list[dict], clave: str) -> str:
    return next((f["tono"] for f in fs if f["clave"] == clave), "")


def grupo_de_piezas(eeuu: list[dict], europa: list[dict]) -> list[str]:
    """Orden de preferencia de los grupos de recursos según el contexto."""
    if tono_de(eeuu, "vix") in ("warn", "bad") or tono_de(eeuu, "trend") == "bad":
        return ["caidas", "general"]
    if tono_de(eeuu, "inflation") in ("warn", "bad") or tono_de(europa, "inflation") in ("warn", "bad"):
        return ["inflacion", "general"]
    return ["general"]


def candidatas(eeuu: list[dict], europa: list[dict], semana: str) -> list[dict]:
    """Recursos posibles para esta semana, en orden: el elegido primero."""
    n = int(semana.split("W")[1])
    lista: list[dict] = []
    for g in grupo_de_piezas(eeuu, europa):
        piezas = PIEZAS[g]
        inicio = n % len(piezas)
        lista += [piezas[(inicio + i) % len(piezas)] for i in range(len(piezas))]
    return lista


def con_utm(url: str, contenido: str) -> str:
    partes = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(partes.query)
    q += list(UTM.items()) + [("utm_content", contenido)]
    return urllib.parse.urlunsplit(partes._replace(query=urllib.parse.urlencode(q)))


def monitor_url() -> str:
    url = os.environ.get("MONITOR_URL", "").strip() or MONITOR_POR_DEFECTO
    return url if url.endswith("/") else url + "/"


# ---------------------------------------------------------------------------
# HTML del email
# ---------------------------------------------------------------------------
def esc(t: str) -> str:
    return html.escape(t or "", quote=True)


def estilo(tam: int, peso: int = 400, color: str = TEXTO, alto: str = "1.6", extra: str = "") -> str:
    return f"font-size:{tam}px;font-weight:{peso};line-height:{alto};color:{color};{extra}"


def antetitulo(texto: str) -> str:
    return (f'<p style="margin:0 0 6px;{estilo(12, 700, DORADO, "1.4", "letter-spacing:.08em;text-transform:uppercase;")}">'
            f'{esc(texto)}</p>')


def fila_html(f: dict) -> str:
    color, borde, fondo = TONOS[f["tono"]]
    etiqueta = (f'<span style="display:inline-block;padding:3px 10px;border:1px solid {borde};border-radius:30px;'
                f'background:{fondo};{estilo(11, 700, color, "1.4", "letter-spacing:.06em;text-transform:uppercase;")}">'
                f'{esc(f["estado"])}</span>')
    return (
        f'<tr><td style="padding:14px 0;border-top:1px solid {LINEA};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="{estilo(16, 700, TEXTO, "1.3")}">{esc(f["nombre"])}</td>'
        f'<td align="right" style="white-space:nowrap;padding-left:10px;">{etiqueta}</td>'
        '</tr></table>'
        f'<p style="margin:6px 0 0;{estilo(15, 400, SUAVE, "1.55")}">{esc(f["texto"])}</p>'
        '</td></tr>'
    )


def seccion_html(titulo: str, subtitulo: str, fs: list[dict]) -> str:
    cuerpo = "".join(fila_html(f) for f in fs)
    return (
        '<tr><td style="padding:22px 0 4px;">'
        f'<p style="margin:0;{estilo(12, 700, DORADO, "1.4", "letter-spacing:.08em;text-transform:uppercase;")}">'
        f'{esc(titulo)}<span style="{estilo(12, 400, PIE, "1.4", "letter-spacing:0;text-transform:none;")}"> · {esc(subtitulo)}</span></p>'
        '</td></tr>'
        f'<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{cuerpo}</table></td></tr>'
    )


def boton(texto: str, url: str, primario: bool) -> str:
    if primario:
        return ('<table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 0;"><tr>'
                '<td style="background:#111111;border-radius:8px;">'
                f'<a href="{esc(url)}" target="_blank" style="display:inline-block;padding:14px 24px;'
                f'text-decoration:none;{estilo(16, 700, "#ffffff", "1.2")}">{esc(texto)}</a></td></tr></table>')
    return ('<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
            '<td style="border:1px solid #d0d7de;border-radius:8px;">'
            f'<a href="{esc(url)}" target="_blank" style="display:inline-block;padding:12px 22px;'
            f'text-decoration:none;{estilo(15, 600, TEXTO, "1.2")}">{esc(texto)}</a></td></tr></table>')


def contexto(us: dict, eu: dict | None) -> dict:
    actualizado = parse_fecha(us["meta"]["updated_at"])
    eeuu = filas(us, BLOQUES_EEUU)
    europa = filas(eu, BLOQUES_EUROPA) if europa_valida(eu, us) else []
    semana = semana_iso(actualizado)
    resumen = []
    if eeuu:
        resumen.append(f"EE. UU.: {conteo(eeuu)}")
    if europa:
        resumen.append(f"Zona euro: {conteo(europa)}")
    return {
        "actualizado": actualizado,
        "semana": semana,
        "campana": f"Market Monitor · {semana}",
        "asunto": ASUNTO.format(fecha=fecha_corta(actualizado)),
        "preheader": " · ".join(resumen),
        "eeuu": eeuu,
        "europa": europa,
        "europa_sin_datos": not europa,
        "pieza": None,
        "monitor": monitor_url(),
    }


def construir_html(c: dict) -> str:
    mon = c["monitor"]
    url_monitor = con_utm(mon, "monitor")
    url_europa = con_utm(mon + "europa.html", "europa")
    url_gratis = con_utm(WEB + "gratis", "modulo0")

    partes = [seccion_html("EE. UU.", "S&P 500, tipos, empleo e inflación", c["eeuu"])]
    if c["europa"]:
        partes.append(seccion_html("Zona euro", "BCE, deuda, empleo e IPCA", c["europa"]))
        partes.append(
            f'<tr><td style="padding:4px 0 0;{estilo(14, 400, SUAVE, "1.55")}">La tendencia del Euro Stoxx 50 se ve en el '
            f'<a href="{esc(url_europa)}" target="_blank" style="color:{TEXTO};">gráfico de la página de Europa</a>.</td></tr>')
    else:
        partes.append(
            f'<tr><td style="padding:18px 0 0;{estilo(14, 400, PIE, "1.55")}">'
            'Los datos de la zona euro no se han podido actualizar esta semana.</td></tr>')

    pieza = ""
    if c["pieza"]:
        p = c["pieza"]
        url_p = con_utm(WEB + p["url"], "recurso")
        pieza = (
            '<tr><td style="padding:24px 0 0;">'
            + antetitulo("Para entender mejor") +
            f'<p style="margin:0;{estilo(16, 700, TEXTO, "1.45")}">'
            f'<a href="{esc(url_p)}" target="_blank" style="color:{TEXTO};text-decoration:underline;">'
            f'{esc(p["tipo"])} · {esc(p["titulo"])}</a></p>'
            f'<p style="margin:4px 0 0;{estilo(15, 400, SUAVE, "1.55")}">{esc(p["texto"])}</p>'
            '</td></tr>')

    cuerpo = "".join(partes)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(c["asunto"])}</title>
</head>
<body style="margin:0;padding:0;background:#eef0f3;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef0f3;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;font-family:{FUENTE};">
<tr><td style="background:#0b0b0c;padding:18px 28px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="width:34px;height:34px;border:2px solid #ffffff;border-radius:50%;text-align:center;font-size:13px;font-weight:800;color:#ffffff;">VQ</td>
<td style="padding-left:12px;font-size:16px;font-weight:700;color:#ffffff;">ValQual Market Monitor</td>
</tr></table>
</td></tr>
<tr><td style="padding:28px 28px 8px;">
{antetitulo("Actualizado el " + fecha_larga(c["actualizado"]))}
<p style="margin:0 0 14px;{estilo(24, 800, TEXTO, "1.25", "letter-spacing:-.01em;")}">El mercado esta semana, sin ruido</p>
<p style="margin:0 0 10px;{estilo(16)}">Una vez por semana, el contexto del mercado en pocas líneas: datos públicos leídos con reglas fijas. Describe el entorno; no es una señal de compra o venta.</p>
<p style="margin:0;{estilo(13, 400, PIE, "1.5")}">Verde: favorable o normal · Ámbar: a vigilar · Rojo: preocupante</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
{cuerpo}
<tr><td style="padding:24px 0 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f8fa;border-left:3px solid {DORADO};border-radius:6px;"><tr><td style="padding:14px 16px;">
<p style="margin:0;{estilo(16, 700, TEXTO, "1.45")}">El contexto cambia; tu proceso, no.</p>
<p style="margin:6px 0 0;{estilo(15, 400, SUAVE, "1.55")}">Estos datos ayudan a entender el entorno en el que inviertes, no a decidir cuándo entrar o salir del mercado. Las caídas y los periodos de tensión forman parte del recorrido normal de la bolsa.</p>
</td></tr></table>
</td></tr>
{pieza}
<tr><td style="padding:24px 0 0;">
{antetitulo("Módulo 0 gratis")}
<p style="margin:0 0 14px;{estilo(16)}">La inflación, los tipos de interés y el ciclo económico se explican en el Módulo 0 de ValQual: 24 lecciones cortas, gratis. Si ya tienes cuenta, entra y sigue donde lo dejaste.</p>
{boton("Empezar el Módulo 0 →", url_gratis, True)}
</td></tr>
<tr><td style="padding:16px 0 24px;">{boton("Ver el Market Monitor completo", url_monitor, False)}</td></tr>
</table>
</td></tr>
<tr><td style="padding:18px 28px 24px;border-top:1px solid {LINEA};">
<p style="margin:0 0 10px;{estilo(12, 400, PIE, "1.5")}">Contenido educativo. No es asesoramiento financiero ni una recomendación de inversión. Invertir implica riesgo de pérdida.</p>
<p style="margin:0 0 10px;{estilo(12, 400, PIE, "1.5")}">Fuentes: FRED (Federal Reserve Bank of St. Louis), U.S. Bureau of Labor Statistics, U.S. Department of Labor, U.S. Treasury, Federal Reserve Bank of Chicago, U.S. Energy Information Administration, Cboe, Banco Central Europeo y Eurostat. Cada dato tiene su propia frecuencia; la página muestra la fecha de cada uno.</p>
<p style="margin:0;{estilo(12, 400, PIE, "1.5")}">Recibes este email porque te suscribiste al Market Monitor de ValQual o aceptaste recibir emails de ValQual. <a href="{{{{ unsubscribe }}}}" style="color:{PIE};">Darme de baja</a> · <a href="https://valqual.app/privacidad.html" style="color:{PIE};">Privacidad</a> · <a href="{{{{ mirror }}}}" style="color:{PIE};">Ver en el navegador</a><br>ValQual · valqual.app · info@valqual.app</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def vista_previa(html_brevo: str) -> str:
    """Versión para abrir en el navegador: sin las etiquetas de Brevo."""
    return html_brevo.replace("{{ mirror }}", "#").replace("{{ unsubscribe }}", "#")


def enlaces(c: dict) -> dict[str, str]:
    """Enlaces del email que se comprueban antes de enviar (sin UTM)."""
    e = {"monitor": c["monitor"], "gratis": WEB + "gratis"}
    if c["europa"]:
        e["europa"] = c["monitor"] + "europa.html"
    return e


# ---------------------------------------------------------------------------
# Red: comprobación de enlaces y API de Brevo
# ---------------------------------------------------------------------------
def comprobar_enlace(url: str, timeout: int = 15) -> str:
    """«ok», «roto» (404 o 410) o «dudoso» (red caída, 403, 5xx…)."""
    resultado = "dudoso"
    for metodo in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=metodo, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if 200 <= r.status < 400:
                    return "ok"
        except urllib.error.HTTPError as e:
            resultado = "roto" if e.code in (404, 410) else "dudoso"
        except Exception:  # noqa: BLE001 - red caída o tiempo agotado
            resultado = "dudoso"
    return resultado


def enlace_ok(url: str) -> bool:
    """Falso solo si la página no existe; si no se puede comprobar, avisa y sigue."""
    estado = comprobar_enlace(url)
    if estado == "dudoso":
        aviso(f"No se pudo comprobar {url}; se envía igualmente.")
    return estado != "roto"


def brevo(clave: str, metodo: str, ruta: str, cuerpo: dict | None = None, params: dict | None = None):
    url = API + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    intentos = 3 if metodo == "GET" else 1  # nunca se repite una petición que crea o envía
    for intento in range(intentos):
        req = urllib.request.Request(url, data=datos, method=metodo, headers={
            "api-key": clave, "accept": "application/json",
            "content-type": "application/json", "user-agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                texto = r.read().decode("utf-8")
                return r.status, (json.loads(texto) if texto.strip() else None)
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(texto)
            except ValueError:
                j = None
            if e.code in (429, 500, 502, 503, 504) and intento < intentos - 1:
                time.sleep(3 * (intento + 1))
                continue
            mensaje = (j or {}).get("message") or texto[:300] or str(e.reason)
            raise BrevoError(e.code, mensaje, j) from None
        except urllib.error.URLError as e:
            if intento < intentos - 1:
                time.sleep(3 * (intento + 1))
                continue
            raise BrevoError(0, f"sin conexión con Brevo ({e.reason})") from None
    raise BrevoError(0, "sin respuesta de Brevo")


def explicar(e: BrevoError) -> str:
    if e.estado == 401:
        return ("Brevo rechaza la clave (401). Puede haber caducado o haberse borrado: crea otra en Brevo "
                "(SMTP y API > Claves API) y guárdala en GitHub como secreto BREVO_API_KEY.")
    if e.estado == 402:
        return ("Brevo dice que no hay créditos suficientes (402): probablemente se ha alcanzado el límite "
                "diario del plan gratuito (300 emails). Prueba mañana o revisa el plan.")
    if e.estado == 0:
        return f"No se pudo hablar con Brevo: {e}"
    return f"Brevo respondió {e.estado}: {e}"


def leer_listas() -> list[int]:
    crudo = os.environ.get("BREVO_LISTAS", "").replace(" ", "")
    if not crudo:
        raise ErrorEnvio("Falta BREVO_LISTAS (los IDs de las listas de Brevo, p. ej. 6 o 6,3,4,5).")
    try:
        listas = [int(x) for x in crudo.split(",") if x]
    except ValueError:
        raise ErrorEnvio(f"BREVO_LISTAS no es válido: «{crudo}». Usa números separados por comas.") from None
    if not listas or any(x <= 0 for x in listas):
        raise ErrorEnvio(f"BREVO_LISTAS no es válido: «{crudo}».")
    return list(dict.fromkeys(listas))


def leer_limite() -> int:
    crudo = os.environ.get("BREVO_LIMITE", "").strip()
    try:
        return int(crudo) if crudo else LIMITE_POR_DEFECTO
    except ValueError:
        raise ErrorEnvio(f"BREVO_LIMITE no es un número: «{crudo}».") from None


def momento_de_envio(ahora: datetime) -> datetime | None:
    """Hora programada de hoy en UTC, o None si ya ha pasado (se envía en el momento)."""
    crudo = os.environ.get("EMAIL_HORA_UTC", "").strip() or HORA_POR_DEFECTO
    try:
        h, m = (int(x) for x in crudo.split(":"))
        objetivo = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    except ValueError:
        raise ErrorEnvio(f"EMAIL_HORA_UTC no es válida: «{crudo}». Usa HH:MM, p. ej. 15:00.") from None
    return objetivo if objetivo - ahora > timedelta(minutes=5) else None


def campana_existente(clave: str, nombre: str) -> dict | None:
    params = {"type": "classic", "limit": 100, "offset": 0, "sort": "desc", "excludeHtmlContent": "true"}
    try:
        _, j = brevo(clave, "GET", "/emailCampaigns", params=params)
    except BrevoError as e:
        if e.estado != 400:
            raise
        params.pop("excludeHtmlContent")
        _, j = brevo(clave, "GET", "/emailCampaigns", params=params)
    for camp in (j or {}).get("campaigns") or []:
        if camp.get("name") == nombre:
            return camp
    return None


def contactos_en_listas(clave: str, listas: list[int]) -> int:
    total = 0
    for lista in listas:
        try:
            _, j = brevo(clave, "GET", f"/contacts/lists/{lista}")
        except BrevoError as e:
            if e.estado == 404:
                raise ErrorEnvio(f"La lista {lista} no existe en Brevo. Revisa BREVO_LISTAS.") from None
            raise
        total += int((j or {}).get("totalSubscribers") or 0)
    return total


def elegir_pieza(c_eeuu: list[dict], c_europa: list[dict], semana: str, comprobar: bool) -> dict | None:
    for p in candidatas(c_eeuu, c_europa, semana):
        if not comprobar or enlace_ok(WEB + p["url"]):
            return p
        aviso(f"El enlace del recurso {WEB + p['url']} no responde: se usa el siguiente.")
    return None


# ---------------------------------------------------------------------------
# Salida para GitHub
# ---------------------------------------------------------------------------
def aviso(texto: str) -> None:
    print(f"AVISO: {texto}")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::{texto}")


def resumen_github(lineas: list[str]) -> None:
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")


def preparar(comprobar: bool) -> tuple[dict, str]:
    us = cargar(DATA_EEUU)
    if not us or "readings" not in us or "meta" not in us:
        raise ErrorEnvio("No se encuentra data/market.json o no tiene lecturas.")
    c = contexto(us, cargar(DATA_EUROPA))
    c["pieza"] = elegir_pieza(c["eeuu"], c["europa"], c["semana"], comprobar)
    return c, construir_html(c)


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------
def construir() -> int:
    c, html_brevo = preparar(comprobar=False)
    SALIDA.mkdir(exist_ok=True)
    (SALIDA / "email.html").write_text(html_brevo, encoding="utf-8")
    (SALIDA / "vista-previa.html").write_text(vista_previa(html_brevo), encoding="utf-8")
    info = {"asunto": c["asunto"], "preheader": c["preheader"], "campana": c["campana"],
            "semana": c["semana"], "recurso": (c["pieza"] or {}).get("url"),
            "filas_eeuu": len(c["eeuu"]), "filas_europa": len(c["europa"]), "bytes": len(html_brevo.encode())}
    (SALIDA / "email.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Email preparado: «{c['asunto']}» ({info['bytes']} bytes).")
    print(f"Resumen: {c['preheader']}")
    if c["europa_sin_datos"]:
        aviso("Los datos de Europa no son de esta semana: el email sale sin la zona euro.")
    return 0


def prueba() -> int:
    clave = os.environ.get("BREVO_API_KEY", "").strip()
    if not clave:
        raise ErrorEnvio("Falta el secreto BREVO_API_KEY.")
    destino = os.environ.get("EMAIL_PRUEBA", "").strip() or "info@valqual.app"
    ahora = ahora_utc()
    c, html_brevo = preparar(comprobar=True)
    for nombre, url in enlaces(c).items():
        if not enlace_ok(url):
            aviso(f"El enlace «{nombre}» ({url}) no existe. En un envío real, no se enviaría.")
    try:
        borrar_pruebas_anteriores(clave)
        try:
            brevo(clave, "POST", "/contacts", {"email": destino, "updateEnabled": True})
        except BrevoError as e:
            if e.estado != 400:  # 400 = el contacto ya existe
                raise
        nombre = f"PRUEBA · {c['campana']} · {ahora:%H%M%S}"
        _, j = brevo(clave, "POST", "/emailCampaigns", {
            "name": nombre, "subject": "[Prueba] " + c["asunto"], "previewText": c["preheader"],
            "sender": REMITENTE, "replyTo": RESPONDER_A, "htmlContent": html_brevo,
            "mirrorActive": True, "inlineImageActivation": False, "tag": "market-monitor-prueba"})
    except BrevoError as e:
        raise ErrorEnvio(explicar(e)) from None
    camp = int(j["id"])
    try:
        brevo(clave, "POST", f"/emailCampaigns/{camp}/sendTest", {"emailTo": [destino]})
    except BrevoError as e:
        detalle = ""
        if e.cuerpo.get("unexistingEmails") or e.cuerpo.get("withoutListEmails"):
            detalle = (f" Brevo no acepta {destino} como destinatario de prueba: añádelo como contacto en "
                       "Brevo (Contactos > Añadir) y repite.")
        borrar_borrador(clave, camp)
        raise ErrorEnvio(explicar(e) + detalle) from None
    print(f"Prueba enviada a {destino}: «[Prueba] {c['asunto']}». "
          f"El borrador «{nombre}» queda en Brevo y se borra en la próxima prueba.")
    resumen_github(["### Email de prueba enviado", f"- Para: {destino}", f"- Asunto: [Prueba] {c['asunto']}"])
    return 0


def borrar_pruebas_anteriores(clave: str) -> None:
    _, j = brevo(clave, "GET", "/emailCampaigns",
                 params={"type": "classic", "status": "draft", "limit": 100, "offset": 0})
    for camp in (j or {}).get("campaigns") or []:
        if str(camp.get("name", "")).startswith("PRUEBA · Market Monitor") and camp.get("status", "draft") == "draft":
            borrar_borrador(clave, int(camp["id"]))


def borrar_borrador(clave: str, camp: int) -> None:
    try:
        brevo(clave, "DELETE", f"/emailCampaigns/{camp}")
    except BrevoError as e:
        aviso(f"No se pudo borrar el borrador {camp} en Brevo ({e}). Se puede borrar a mano.")


def enviar() -> int:
    if os.environ.get("EMAIL_SEMANAL", "").strip().lower() != "on":
        print("El email semanal está apagado (EMAIL_SEMANAL no vale «on»): no se envía nada.")
        return 0
    clave = os.environ.get("BREVO_API_KEY", "").strip()
    if not clave:
        raise ErrorEnvio("Falta el secreto BREVO_API_KEY.")
    listas = leer_listas()
    limite = leer_limite()
    ahora = ahora_utc()

    us = cargar(DATA_EEUU)
    if not us or not es_fresco(us, ahora):
        raise ErrorEnvio("Los datos de EE. UU. no son de los últimos 3 días o son de demostración: "
                         "no se envía el email de esta semana.")

    c, html_brevo = preparar(comprobar=True)
    if len(c["eeuu"]) < 3:
        raise ErrorEnvio(f"El resumen de EE. UU. solo tiene {len(c['eeuu'])} bloques: algo ha cambiado en "
                         "data/market.json. No se envía.")
    rotos = [f"{n} ({u})" for n, u in enlaces(c).items() if not enlace_ok(u)]
    if rotos:
        raise ErrorEnvio("Estos enlaces del email no existen: " + ", ".join(rotos) + ". No se envía.")

    try:
        existente = campana_existente(clave, c["campana"])
        if existente and existente.get("status") != "draft":
            print(f"Ya hay una campaña «{c['campana']}» en Brevo (estado: {existente.get('status')}). "
                  "No se envía otra esta semana.")
            return 0
        if existente:  # borrador de un intento anterior: se rehace
            brevo(clave, "DELETE", f"/emailCampaigns/{existente['id']}")

        total = contactos_en_listas(clave, listas)
        if total == 0:
            print(f"Las listas {listas} no tienen contactos: no se envía nada.")
            return 0
        if total > limite:
            raise ErrorEnvio(f"Las listas suman {total} contactos y el límite es {limite} "
                             "(el plan gratuito de Brevo permite 300 emails al día). No se envía. "
                             "Sube BREVO_LIMITE si el plan lo permite.")

        programada = momento_de_envio(ahora)
        cuerpo = {"name": c["campana"], "subject": c["asunto"], "previewText": c["preheader"],
                  "sender": REMITENTE, "replyTo": RESPONDER_A, "htmlContent": html_brevo,
                  "recipients": {"listIds": listas}, "mirrorActive": True,
                  "inlineImageActivation": False, "tag": "market-monitor"}
        if programada:
            cuerpo["scheduledAt"] = programada.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        try:
            _, j = brevo(clave, "POST", "/emailCampaigns", cuerpo)
        except BrevoError as e:
            if not (programada and e.estado == 400 and "schedul" in str(e).lower()):
                raise
            aviso(f"Brevo no deja programar la campaña ({e}): se envía en el momento.")
            cuerpo.pop("scheduledAt")
            programada = None
            _, j = brevo(clave, "POST", "/emailCampaigns", cuerpo)
        camp = int(j["id"])
        if not programada:
            brevo(clave, "POST", f"/emailCampaigns/{camp}/sendNow")
    except BrevoError as e:
        raise ErrorEnvio(explicar(e)) from None

    cuando = f"programada para las {programada:%H:%M} UTC" if programada else "enviada ahora"
    print(f"Campaña «{c['campana']}» (ID {camp}) {cuando} a las listas {listas} ({total} contactos).")
    print(f"Asunto: «{c['asunto']}». Recurso: {(c['pieza'] or {}).get('url', 'ninguno')}.")
    resumen_github([f"### Email semanal: {cuando}", f"- Campaña: {c['campana']} (ID {camp})",
                    f"- Listas: {', '.join(map(str, listas))} · {total} contactos",
                    f"- Asunto: {c['asunto']}", f"- Resumen: {c['preheader']}"])
    return 0


def main(argv: list[str]) -> int:
    orden = argv[1] if len(argv) > 1 else ""
    acciones = {"construir": construir, "prueba": prueba, "enviar": enviar}
    if orden not in acciones:
        print(__doc__)
        return 2
    try:
        return acciones[orden]()
    except ErrorEnvio as e:
        print(f"ERROR: {e}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error::{e}")
        resumen_github(["### Email semanal: no enviado", str(e)])
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
