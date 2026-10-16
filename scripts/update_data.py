#!/usr/bin/env python3
"""
ValQual Market Monitor - actualización semanal de datos.

Descarga series públicas de FRED (Federal Reserve Bank of St. Louis), calcula
indicadores derivados (SMA 200, distancias, variaciones, IPC interanual) y
escribe data/market.json, que la página index.html lee al abrirse.

Uso:
    python scripts/update_data.py            # datos reales de FRED
    python scripts/update_data.py --demo     # datos sintéticos para probar el diseño

No necesita clave: usa la descarga CSV pública de FRED. Si existe la variable
de entorno FRED_API_KEY, usa la API oficial (más estable) en su lugar.
Solo usa la biblioteca estándar de Python.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "market.json"

# ---------------------------------------------------------------------------
# Series y metadatos
# ---------------------------------------------------------------------------
SERIES = {
    "SP500":        {"name": "S&P 500",                          "freq": "D", "unit": "pts", "digits": 0, "source": "S&P Dow Jones Indices LLC vía FRED"},
    "VIXCLS":       {"name": "VIX · volatilidad implícita",      "freq": "D", "unit": "",    "digits": 1, "source": "Cboe vía FRED"},
    "DGS10":        {"name": "Bono del Tesoro EE. UU. 10 años",  "freq": "D", "unit": "%",   "digits": 2, "source": "U.S. Treasury vía FRED"},
    "T10Y2Y":       {"name": "Curva de tipos 10 años – 2 años",  "freq": "D", "unit": "pp",  "digits": 2, "source": "U.S. Treasury vía FRED"},
    "NFCI":         {"name": "Condiciones financieras (NFCI)",   "freq": "W", "unit": "",    "digits": 2, "source": "Federal Reserve Bank of Chicago vía FRED"},
    "UNRATE":       {"name": "Tasa de desempleo U-3",            "freq": "M", "unit": "%",   "digits": 1, "source": "U.S. Bureau of Labor Statistics vía FRED"},
    "SAHMREALTIME": {"name": "Regla de Sahm (tiempo real)",      "freq": "M", "unit": "pp",  "digits": 2, "source": "Claudia Sahm / FRED"},
    "ICSA":         {"name": "Solicitudes iniciales de subsidio", "freq": "W", "unit": "",   "digits": 0, "source": "U.S. Department of Labor vía FRED"},
    "CPIAUCSL":     {"name": "IPC EE. UU. (índice)",             "freq": "M", "unit": "",    "digits": 1, "source": "U.S. Bureau of Labor Statistics vía FRED"},
    "DCOILWTICO":   {"name": "Petróleo WTI",                     "freq": "D", "unit": "$",   "digits": 2, "source": "U.S. Energy Information Administration vía FRED"},
}

# Años de historia a descargar por frecuencia (la SMA 200 necesita ~1 año extra)
HISTORY_YEARS = {"D": 3, "W": 3, "M": 6}


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/json,text/plain,*/*",
}


def _get(url: str, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {last}")


def fetch_fred(series_id: str, start: date) -> list[tuple[date, float]]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    rows: list[tuple[date, float]] = []
    if key:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
               f"&api_key={key}&file_type=json&observation_start={start.isoformat()}")
        data = json.loads(_get(url))
        for o in data.get("observations", []):
            v = o.get("value", ".")
            if v not in (".", ""):
                rows.append((date.fromisoformat(o["date"]), float(v)))
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start.isoformat()}"
        text = _get(url)
        reader = csv.reader(io.StringIO(text))
        next(reader, None)  # cabecera
        for rec in reader:
            if len(rec) < 2:
                continue
            v = rec[1].strip()
            if v in (".", ""):
                continue
            try:
                rows.append((date.fromisoformat(rec[0].strip()), float(v)))
            except ValueError:
                continue
    if len(rows) < 3:
        raise RuntimeError(f"Serie {series_id} sin suficientes observaciones")
    rows.sort()
    return rows


# ---------------------------------------------------------------------------
# Datos sintéticos (solo para probar el diseño; la página los marca como DEMO)
# ---------------------------------------------------------------------------
def demo_series(series_id: str, start: date, today: date) -> list[tuple[date, float]]:
    rnd = random.Random(sum(map(ord, series_id)))
    freq = SERIES[series_id]["freq"]
    pts: list[date] = []
    d = start
    while d <= today:
        if freq == "D" and d.weekday() < 5:
            pts.append(d)
        elif freq == "W" and d.weekday() == (5 if series_id == "ICSA" else 4):
            pts.append(d)
        elif freq == "M" and d.day == 1:
            pts.append(d)
        d += timedelta(days=1)
    if freq == "M":
        pts = pts[:-1]  # el último mes aún no publicado
    base = {"SP500": 4200, "VIXCLS": 16, "DGS10": 4.1, "T10Y2Y": 0.3, "NFCI": -0.45,
            "UNRATE": 3.8, "SAHMREALTIME": 0.2, "ICSA": 225000, "CPIAUCSL": 300, "DCOILWTICO": 75}[series_id]
    out, v = [], base
    for i, p in enumerate(pts):
        if series_id == "SP500":
            v *= 1 + rnd.gauss(0.0004, 0.009)
        elif series_id == "CPIAUCSL":
            v *= 1 + rnd.gauss(0.0024, 0.001)
        elif series_id == "ICSA":
            v = max(180000, v + rnd.gauss(0, 7000))
        elif series_id == "VIXCLS":
            v = max(10, v + rnd.gauss(0, 0.9) - 0.05 * (v - 16))
        else:
            v = v + rnd.gauss(0, abs(base) * 0.012 + 0.01)
        out.append((p, round(v, 4)))
    return out


# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------
def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def value_on_or_before(rows: list[tuple[date, float]], target: date) -> tuple[date, float] | None:
    best = None
    for d, v in rows:
        if d <= target:
            best = (d, v)
        else:
            break
    return best


def comparison(rows, freq):
    """Último dato y dato de comparación: hace 1 semana (diarias) o publicación anterior."""
    last_d, last_v = rows[-1]
    if freq == "D":
        prev = value_on_or_before(rows, last_d - timedelta(days=7))
    else:
        prev = rows[-2]
    return (last_d, last_v), prev


def downsample(rows, keep_from: date, step: int = 1):
    sel = [(d, v) for d, v in rows if d >= keep_from]
    return sel[::step] if step > 1 else sel


def r(x, n=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)


def indicator_block(sid, rows, history_from, step=1, transform_name=None):
    meta = SERIES[sid]
    (ld, lv), prev = comparison(rows, meta["freq"])
    block = {
        "id": sid,
        "name": transform_name or meta["name"],
        "unit": meta["unit"],
        "digits": meta["digits"],
        "freq": meta["freq"],
        "source": meta["source"],
        "fred_url": f"https://fred.stlouisfed.org/series/{sid}",
        "last": r(lv), "last_date": ld.isoformat(),
        "prev": r(prev[1]) if prev else None, "prev_date": prev[0].isoformat() if prev else None,
        "change": r(lv - prev[1]) if prev else None,
        "history": [[d.isoformat(), r(v)] for d, v in downsample(rows, history_from, step)],
    }
    return block


# ---------------------------------------------------------------------------
# Lecturas (reglas fijas, descriptivas; nunca señales de compra/venta)
# ---------------------------------------------------------------------------
def fmt_es(x, digits=1):
    s = f"{x:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def readings(d):
    out = {}
    sp = d["sp500"]
    dist = sp["distance_pct"]
    if dist >= 0:
        out["trend"] = ("positiva", f"El S&P 500 cotiza un {fmt_es(dist)} % por encima de su media de 200 sesiones"
                        + (", y la media sigue subiendo." if sp["sma_slope_pct"] > 0 else ", aunque la media ha dejado de subir."))
    else:
        out["trend"] = ("débil", f"El S&P 500 cotiza un {fmt_es(abs(dist))} % por debajo de su media de 200 sesiones"
                        + (", y la media está bajando." if sp["sma_slope_pct"] < 0 else ", aunque la media todavía sube."))

    vix = d["indicators"]["VIXCLS"]["last"]
    if vix < 15:
        out["vix"] = ("calma", f"El VIX ({fmt_es(vix)}) refleja un mercado tranquilo, con baja volatilidad esperada.")
    elif vix < 20:
        out["vix"] = ("normal", f"El VIX ({fmt_es(vix)}) está en niveles habituales.")
    elif vix < 30:
        out["vix"] = ("tensión", f"El VIX ({fmt_es(vix)}) señala nerviosismo por encima de lo habitual.")
    else:
        out["vix"] = ("estrés", f"El VIX ({fmt_es(vix)}) está en niveles de estrés elevado.")

    curve = d["indicators"]["T10Y2Y"]["last"]
    nfci = d["indicators"]["NFCI"]["last"]
    curve_txt = ("la curva de tipos está invertida (el bono a 2 años rinde más que el de 10)" if curve < 0
                 else "la curva de tipos tiene pendiente positiva")
    nfci_txt = ("las condiciones financieras son más holgadas que la media histórica" if nfci < 0
                else "las condiciones financieras son más restrictivas que la media histórica")
    out["financial"] = ("holgadas" if nfci < 0 else "restrictivas",
                        f"El bono a 10 años rinde un {fmt_es(d['indicators']['DGS10']['last'], 2)} %, {curve_txt} y {nfci_txt}.")

    sahm = d["indicators"]["SAHMREALTIME"]["last"]
    un = d["indicators"]["UNRATE"]
    icsa4 = d["icsa_4w_avg"]
    if sahm >= 0.5:
        out["cycle"] = ("alerta", f"La regla de Sahm ({fmt_es(sahm, 2)}) supera el umbral de 0,50 que históricamente ha acompañado a las recesiones.")
    else:
        trend = "sube" if (un["change"] or 0) > 0 else ("baja" if (un["change"] or 0) < 0 else "se mantiene")
        out["cycle"] = ("sin señal", f"El desempleo ({fmt_es(un['last'])} %) {trend} y la regla de Sahm ({fmt_es(sahm, 2)}) sigue por debajo del umbral de 0,50. "
                        f"Media de 4 semanas de solicitudes iniciales: {fmt_es(icsa4, 0)}.")

    cpi = d["cpi_yoy"]["last"]
    oil = d["indicators"]["DCOILWTICO"]
    out["inflation"] = ("cerca del objetivo" if cpi <= 2.5 else "por encima del objetivo",
                        f"La inflación interanual (IPC) es del {fmt_es(cpi)} %, frente al objetivo del 2 % de la Reserva Federal. "
                        f"El petróleo WTI cotiza a {fmt_es(oil['last'], 2)} $ por barril.")
    return out


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def main(demo: bool = False):
    sys.stdout.reconfigure(line_buffering=True)
    today = datetime.now(timezone.utc).date()
    raw: dict[str, list[tuple[date, float]]] = {}
    errors = []
    for sid, meta in SERIES.items():
        start = today - timedelta(days=365 * HISTORY_YEARS[meta["freq"]])
        print(f"... {sid}")
        try:
            raw[sid] = demo_series(sid, start, today) if demo else fetch_fred(sid, start)
            print(f"OK  {sid}: {len(raw[sid])} obs, último {raw[sid][-1][0]}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}: {e}")
            print(f"ERR {sid}: {e}", file=sys.stderr)

    if errors:
        # No sobrescribimos el JSON anterior con datos incompletos.
        print("Errores de descarga; se conserva el market.json anterior.", file=sys.stderr)
        sys.exit(1)

    two_years = today - timedelta(days=730)
    five_years = today - timedelta(days=365 * 5)

    # --- S&P 500 + SMA 200
    sp = raw["SP500"]
    closes = [v for _, v in sp]
    s200 = sma(closes, 200)
    last_close, last_sma = closes[-1], s200[-1]
    sma_20_ago = s200[-21] if len(s200) > 21 else None
    wk = value_on_or_before(sp, sp[-1][0] - timedelta(days=7))
    m3 = value_on_or_before(sp, sp[-1][0] - timedelta(days=91))
    ytd_base = value_on_or_before(sp, date(sp[-1][0].year - 1, 12, 31))
    sp_hist = [[d.isoformat(), r(v, 2), r(s, 2)] for (d, v), s in zip(sp, s200) if d >= two_years]

    sp500 = {
        "name": "S&P 500", "source": SERIES["SP500"]["source"],
        "fred_url": "https://fred.stlouisfed.org/series/SP500",
        "last": r(last_close, 2), "last_date": sp[-1][0].isoformat(),
        "sma200": r(last_sma, 2),
        "distance_pct": r((last_close / last_sma - 1) * 100, 2),
        "sma_slope_pct": r((last_sma / sma_20_ago - 1) * 100, 2) if sma_20_ago else 0,
        "chg_1w_pct": r((last_close / wk[1] - 1) * 100, 2) if wk else None,
        "chg_3m_pct": r((last_close / m3[1] - 1) * 100, 2) if m3 else None,
        "chg_ytd_pct": r((last_close / ytd_base[1] - 1) * 100, 2) if ytd_base else None,
        "history": sp_hist,
    }

    # --- Indicadores simples
    ind = {}
    for sid in ["VIXCLS", "DGS10", "T10Y2Y", "DCOILWTICO"]:
        ind[sid] = indicator_block(sid, raw[sid], two_years, step=1)
    for sid in ["NFCI", "ICSA"]:
        ind[sid] = indicator_block(sid, raw[sid], two_years)
    for sid in ["UNRATE", "SAHMREALTIME"]:
        ind[sid] = indicator_block(sid, raw[sid], five_years)

    # --- IPC interanual
    cpi = raw["CPIAUCSL"]
    yoy = []
    idx = {d: v for d, v in cpi}
    for d, v in cpi:
        prev_year = date(d.year - 1, d.month, 1)
        if prev_year in idx:
            yoy.append((d, (v / idx[prev_year] - 1) * 100))
    cpi_yoy = {
        "id": "CPIAUCSL", "name": "Inflación IPC interanual", "unit": "%", "digits": 1, "freq": "M",
        "source": SERIES["CPIAUCSL"]["source"], "fred_url": "https://fred.stlouisfed.org/series/CPIAUCSL",
        "last": r(yoy[-1][1], 2), "last_date": yoy[-1][0].isoformat(),
        "prev": r(yoy[-2][1], 2), "prev_date": yoy[-2][0].isoformat(),
        "change": r(yoy[-1][1] - yoy[-2][1], 2),
        "history": [[d.isoformat(), r(v, 2)] for d, v in yoy if d >= five_years],
    }

    icsa_vals = [v for _, v in raw["ICSA"]]
    icsa_4w = sum(icsa_vals[-4:]) / 4

    data = {
        "meta": {
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "demo": demo,
            "note": "Datos sintéticos de demostración. NO son datos de mercado." if demo else "Datos públicos de FRED.",
        },
        "sp500": sp500,
        "indicators": ind,
        "cpi_yoy": cpi_yoy,
        "icsa_4w_avg": r(icsa_4w, 0),
    }
    data["readings"] = {k: {"label": v[0], "text": v[1]} for k, v in readings(data).items()}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Escrito {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
