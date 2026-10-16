# ValQual Market Monitor

Página gratuita que muestra el estado del mercado estadounidense en cinco bloques y **se actualiza sola cada semana**.

## Cómo funciona

```
Cada sábado ──► GitHub Actions ejecuta scripts/update_data.py
                 │  descarga 10 series públicas de FRED
                 │  calcula SMA 200D, variaciones, IPC interanual y el resumen
                 ▼
               data/market.json  ──►  index.html lo lee al abrirse
```

Coste: 0 €. No requiere servidor, base de datos ni clave de API.

## Datos incluidos

| Bloque | Dato | Serie FRED | Frecuencia |
|---|---|---|---|
| 1 · Tendencia | S&P 500 + SMA 200D (calculada) | `SP500` | Diaria |
| | VIX | `VIXCLS` | Diaria |
| 2 · Condiciones financieras | Bono 10 años | `DGS10` | Diaria |
| | Curva 10A–2A | `T10Y2Y` | Diaria |
| | NFCI (Fed de Chicago) | `NFCI` | Semanal |
| 3 · Ciclo | Desempleo U-3 | `UNRATE` | Mensual |
| | Regla de Sahm | `SAHMREALTIME` | Mensual |
| | Solicitudes iniciales (+ media 4 sem.) | `ICSA` | Semanal |
| 4 · Amplitud | SPY frente a RSP | widget TradingView | En directo |
| 5 · Inflación | IPC interanual (calculado) | `CPIAUCSL` | Mensual |
| | Petróleo WTI | `DCOILWTICO` | Diaria |
| | Oro | widget TradingView | En directo |

## Mantenimiento

- La tarea **Actualizar Market Monitor** (pestaña Actions) se ejecuta cada sábado a las 08:00 UTC; también se puede lanzar a mano con *Run workflow*.
- **Si una descarga falla**, el script no sobrescribe los datos: se conservan los de la semana anterior y GitHub te avisa por email.
- **GitHub pausa las tareas programadas tras 60 días sin actividad** en el repositorio. Si ocurre, te avisa por email y se reactiva con un clic en la pestaña Actions.
- **Opcional, más estabilidad:** solicita una clave gratuita en fred.stlouisfed.org (*My Account → API Keys*) y guárdala como secreto `FRED_API_KEY`. El script la usará automáticamente.
- **Probar el diseño sin conexión:** `python scripts/update_data.py --demo` genera datos sintéticos (la página los marca como DEMO).

## Alternativa: Firebase Hosting (dentro de ValQual)

Descomenta el bloque final de `.github/workflows/actualizar-datos.yml` y añade el secreto `FIREBASE_SERVICE_ACCOUNT`.

## Aviso sobre licencias

Los datos de BLS, DOL, Tesoro, EIA y la Fed de Chicago son de dominio público. La serie `SP500`
es © S&P Dow Jones Indices LLC: se cita su procedencia en la página. Si la página pasa a tener
uso comercial, revisa las condiciones de FRED para series con copyright.
