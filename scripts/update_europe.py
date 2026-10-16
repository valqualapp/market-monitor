#!/usr/bin/env python3
"""
ValQual Market Monitor · Europa - actualización semanal de datos.

Fuentes gratuitas:
  - Banco Central Europeo (data-api.ecb.europa.eu, sin clave): tipo de depósito,
    curva de tipos de la zona euro, CISS, desempleo e IPCA.
  - FRED (misma clave FRED_API_KEY que la versión de EE. UU.): petróleo Brent.
El Euro Stoxx 50 se muestra con un widget de TradingView (no hay fuente gratuita
de datos diarios del índice).

Uso:
    python scripts/update_europe.py          # datos reales
    python scripts/update_europe.py --demo   # datos sintéticos para probar el diseño
"""
from __future__ import annotations

import csv
import io
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_data import _get, fetch_fred, value_on_or_before, r, fmt_es  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "europe.json"

ECB = "https://data-api.ecb.europa.eu/service/data/"

SERIES = {
    "DFR":   {"src": "ecb", "key": "FM/D.U2.EUR.4F.KR.DFR.LEV", "name": "Tipo de depósito del BCE", "freq": "D", "unit": "%", "digits": 2,
              "source": "Banco Central Europeo", "url": "https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV"},
    "Y10":   {"src": "ecb", "key": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "name": "Bono zona euro 10 años (AAA)", "freq": "D", "unit": "%", "digits": 2,
              "source": "Banco Central Europeo", "url": "https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"},
    "Y2":    {"src": "ecb", "key": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y", "name": "Bono zona euro 2 años (AAA)", "freq": "D", "unit": "%", "digits": 2,
              "source": "Banco Central Europeo", "url": "https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"},
    "CISS":  {"src": "ecb", "key": "CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX", "name": "Estrés financiero (CISS)", "freq": "D", "unit": "", "digits": 2,
              "source": "Banco Central Europeo", "url": "https://data.ecb.europa.eu/data/datasets/CISS/CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX"},
    "UNEMP": {"src": "ecb", "key": "LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T", "name": "Tasa de desempleo zona euro", "freq": "M", "unit": "%", "digits": 1,
              "source": "Eurostat vía BCE", "url": "https://data.ecb.europa.eu/data/datasets/LFSI/LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.T"},
    "HICP":  {"src": "ecb", "key": "HICP/M.U2.N.000000.4D0.ANR", "name": "Inflación IPCA interanual", "freq": "M", "unit": "%", "digits": 1,
              "source": "Eurostat vía BCE", "url": "https://data.ecb.europa.eu/data/datasets/HICP/HICP.M.U2.N.000000.4D0.ANR"},
    "BRENT": {"src": "fred", "key": "DCOILBRENTEU", "name": "Petróleo Brent", "freq": "D", "unit": "$", "digits": 2,
              "source": "U.S. Energy Information Administration vía FRED", "url": "https://fred.stlouisfed.org/series/DCOILBRENTEU"},
}


def _period(p: str) -> date:
    p = p.strip()
    if len(p) == 7:  # 2026-09
        return date(int(p[:4]), int(p[5:7]), 1)
    return date.fromisoformat(p[:10])


def fetch_ecb(key: str, start: date) -> list[tuple[date, float]]:
    url = f"{ECB}{key}?format=csvdata&detail=dataonly&startPeriod={start.isoformat()}"
    rows = []
    for rec in csv.DictReader(io.StringIO(_get(url))):
        v = (rec.get("OBS_VALUE") or "").strip()
        t = rec.get("TIME_PERIOD") or ""
        if not v or not t:
            continue
        try:
            rows.append((_period(t), float(v)))
        except ValueError:
            continue
    if len(rows) < 3:
        raise RuntimeError(f"Serie {key} sin suficientes observaciones")
    rows.sort()
    return rows


def demo_series(sid, start, today):
    rnd = random.Random(sum(map(ord, sid)))
    freq = SERIES[sid]["freq"]
    base = {"DFR": 2.5, "Y10": 3.2, "Y2": 2.7, "CISS": 0.08, "UNEMP": 6.4, "HICP": 2.4, "BRENT": 80}[sid]
    out, v, d = [], base, start
    while d <= today:
        ok = (freq == "D" and d.weekday() < 5) or (freq == "M" and d.day == 1 and d < today.replace(day=1))
        if ok:
            if sid == "DFR":
                v = v if rnd.random() > 0.01 else round(v - 0.25, 2)
            else:
                v = max(0.005, v + rnd.gauss(0, abs(base) * 0.01 + 0.005))
            out.append((d, round(v, 4)))
        d += timedelta(days=1)
    return out


def block(sid, rows, history_from, compare="week"):
    m = SERIES[sid]
    ld, lv = rows[-1]
    if compare == "week":
        prev = value_on_or_before(rows, ld - timedelta(days=7))
    else:
        prev = rows[-2]
    return {
        "id": sid, "name": m["name"], "unit": m["unit"], "digits": m["digits"], "freq": m["freq"],
        "source": m["source"], "url": m["url"],
        "last": r(lv), "last_date": ld.isoformat(),
        "prev": r(prev[1]) if prev else None, "prev_date": prev[0].isoformat() if prev else None,
        "change": r(lv - prev[1]) if prev else None,
        "history": [[d.isoformat(), r(v)] for d, v in rows if d >= history_from],
    }


def readings(d):
    I = d["indicators"]
    out = {}
    out["trend"] = ("ver gráfico", "",
                    "Compara el Euro Stoxx 50 con su media de 200 sesiones en el gráfico del bloque 01: "
                    "por encima indica una tendencia de fondo positiva; por debajo, débil.")

    dfr, y10, curve, ciss = I["DFR"], I["Y10"], I["CURVE"], I["CISS"]
    dfr3 = d["dfr_change_3m"]
    if dfr3 < 0:
        bce = f"El BCE ha bajado el tipo de depósito {fmt_es(abs(dfr3), 2)} pp en los últimos tres meses, hasta el {fmt_es(dfr['last'], 2)} %"
    elif dfr3 > 0:
        bce = f"El BCE ha subido el tipo de depósito {fmt_es(dfr3, 2)} pp en los últimos tres meses, hasta el {fmt_es(dfr['last'], 2)} %"
    else:
        bce = f"El BCE mantiene el tipo de depósito en el {fmt_es(dfr['last'], 2)} %"
    curve_txt = "la curva de tipos tiene pendiente positiva" if curve["last"] >= 0 else "la curva de tipos está invertida"
    stress = ciss["last"]
    stress_txt = ("el estrés financiero es bajo" if stress < 0.15 else
                  "el estrés financiero es moderado" if stress < 0.30 else "el estrés financiero es elevado")
    ok_ciss, ok_curve = stress < 0.15, curve["last"] >= 0
    tone = "good" if (ok_ciss and ok_curve) else ("bad" if (stress >= 0.30 or (not ok_ciss and not ok_curve)) else "warn")
    label = {"good": "holgadas", "warn": "a vigilar", "bad": "tensionadas"}[tone]
    out["financial"] = (label, tone, f"{bce}; el bono a 10 años rinde un {fmt_es(y10['last'], 2)} %, {curve_txt} y {stress_txt} (CISS {fmt_es(stress, 2)}).")

    un = I["UNEMP"]
    ch = d["unemp_change_12m"]
    tone = "good" if ch <= 0 else ("warn" if ch < 0.5 else "bad")
    label = {"good": "estable", "warn": "a vigilar", "bad": "deterioro"}[tone]
    trend = "baja" if ch < 0 else ("sube" if ch > 0 else "se mantiene")
    out["cycle"] = (label, tone, f"El desempleo de la zona euro es del {fmt_es(un['last'])} % y {trend} "
                                 f"{fmt_es(abs(ch))} pp respecto a hace un año." if ch else
                    f"El desempleo de la zona euro es del {fmt_es(un['last'])} %, igual que hace un año.")

    h = I["HICP"]["last"]
    tone = "good" if h <= 2.5 else ("warn" if h <= 4 else "bad")
    label = "cerca del objetivo" if h <= 2.5 else "por encima del objetivo"
    out["inflation"] = (label, tone, f"La inflación interanual (IPCA) es del {fmt_es(h)} %, frente al objetivo del 2 % del BCE. "
                                     f"El petróleo Brent cotiza a {fmt_es(I['BRENT']['last'], 2)} $ por barril.")
    return {k: {"label": a, "tone": b, "text": c} for k, (a, b, c) in out.items()}


def main(demo=False):
    sys.stdout.reconfigure(line_buffering=True)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=365 * 6)
    raw, errors = {}, []
    for sid, m in SERIES.items():
        print(f"... {sid}")
        try:
            if demo:
                raw[sid] = demo_series(sid, start, today)
            elif m["src"] == "ecb":
                raw[sid] = fetch_ecb(m["key"], start)
            else:
                raw[sid] = fetch_fred(m["key"], start)
            print(f"OK  {sid}: {len(raw[sid])} obs, último {raw[sid][-1][0]}")
        except Exception as e:  # noqa: BLE001
            errors.append(sid)
            print(f"ERR {sid}: {e}", file=sys.stderr)
    if errors:
        print("Errores de descarga; se conserva el europe.json anterior.", file=sys.stderr)
        sys.exit(1)

    two_years = today - timedelta(days=730)
    five_years = today - timedelta(days=365 * 5)

    # Curva 10A - 2A (mismas fechas)
    y2 = dict(raw["Y2"])
    curve_rows = [(d, v - y2[d]) for d, v in raw["Y10"] if d in y2]
    SERIES["CURVE"] = {"name": "Curva de tipos 10 años – 2 años", "freq": "D", "unit": "pp", "digits": 2,
                       "source": "Banco Central Europeo", "url": SERIES["Y10"]["url"]}

    ind = {
        "DFR": block("DFR", raw["DFR"], five_years),
        "Y10": block("Y10", raw["Y10"], two_years),
        "CURVE": block("CURVE", curve_rows, two_years),
        "CISS": block("CISS", raw["CISS"], two_years),
        "UNEMP": block("UNEMP", raw["UNEMP"], five_years, compare="prev"),
        "HICP": block("HICP", raw["HICP"], five_years, compare="prev"),
        "BRENT": block("BRENT", raw["BRENT"], two_years),
    }
    dfr_rows = raw["DFR"]
    d3 = value_on_or_before(dfr_rows, dfr_rows[-1][0] - timedelta(days=91))
    un = raw["UNEMP"]
    u12 = value_on_or_before(un, date(un[-1][0].year - 1, un[-1][0].month, 1))

    data = {
        "meta": {"updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "demo": demo},
        "indicators": ind,
        "dfr_change_3m": r(dfr_rows[-1][1] - d3[1], 2) if d3 else 0,
        "unemp_change_12m": r(un[-1][1] - u12[1], 2) if u12 else 0,
    }
    data["readings"] = readings(data)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Escrito {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
