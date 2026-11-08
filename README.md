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

## Email semanal (Brevo)

Cada sábado, después de actualizar los datos, la tarea prepara un email con el resumen de la semana
(semáforos de EE. UU. y zona euro, un recurso de valqual.app y el Módulo 0) y, si está encendido,
lo envía como campaña de Brevo. Script: `scripts/email_semanal.py` (solo biblioteca estándar).

- **Se prepara siempre** y se guarda como artefacto `email-semanal` de cada ejecución (vista previa).
- **Solo se envía** si la variable `EMAIL_SEMANAL` vale `on`. Por defecto no se envía nada.
- **Una vez por semana:** la campaña se llama `Market Monitor · AAAA-Wnn`; si ya existe, no se repite.
- **Sale a las 15:00 UTC del sábado** (9:00 en Ciudad de México, 16:00 en Madrid en invierno).
- No se envía si los datos de EE. UU. no son de los últimos 3 días, si las listas superan el límite
  diario del plan gratuito o si algún enlace del email no responde. En ese caso, GitHub avisa por email.
- No reproduce valores del S&P 500 ni del VIX (series con copyright): usa las lecturas y los tramos.

**Puesta en marcha** (Settings → Secrets and variables → Actions):

| Tipo | Nombre | Valor |
|---|---|---|
| Secreto | `BREVO_API_KEY` | Clave de Brevo (SMTP y API → Claves API), sin vencimiento |
| Variable | `BREVO_LISTAS` | IDs de las listas, p. ej. `6` (suscriptores del Monitor) o `6,3,4,5` |
| Variable | `EMAIL_PRUEBA` | Opcional. Destinatario de la prueba (por defecto `info@valqual.app`) |
| Variable | `EMAIL_SEMANAL` | `on` para enviar de verdad; cualquier otro valor lo apaga |
| Variable | `EMAIL_HORA_UTC` | Opcional. Hora de envío en UTC, `HH:MM` (por defecto `15:00`) |
| Variable | `MONITOR_URL` | Opcional. Dirección pública del Monitor si cambia de dominio |
| Variable | `BREVO_LIMITE` | Opcional. Máximo de contactos por envío (por defecto 280) |

**Probar:** Actions → *Actualizar Market Monitor* → *Run workflow* → email `prueba`. Llega a `EMAIL_PRUEBA`
con el asunto «[Prueba] …» y no toca las listas.

**Suscripción en la página:** pega en `config.json` (`suscripcion_url`) el enlace para compartir del
formulario de Brevo. Mientras esté vacío, la sección «Recíbelo cada sábado» no aparece.

## Alternativa: Firebase Hosting (dentro de ValQual)

Descomenta el bloque final de `.github/workflows/actualizar-datos.yml` y añade el secreto `FIREBASE_SERVICE_ACCOUNT`.

## Aviso sobre licencias

Los datos de BLS, DOL, Tesoro, EIA y la Fed de Chicago son de dominio público. La serie `SP500`
es © S&P Dow Jones Indices LLC: se cita su procedencia en la página. Si la página pasa a tener
uso comercial, revisa las condiciones de FRED para series con copyright.
