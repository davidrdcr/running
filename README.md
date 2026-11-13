# running

Dashboard de entrenamiento para maratón con datos de un Garmin Forerunner 570.
Página: https://davidrdcr.github.io/running/

## Estructura

```
index.html               dashboard principal
actividad.html           vista de cada actividad (mapa + datos segundo a segundo)
plan.html                plan hacia la Maratón de Lima (23 may 2027): semana actual, volumen, fases, zonas y fuentes
dia.html                 vista de cada día (FC 24 h, estrés, Body Battery, sueño por fases, HRV, respiración)
raw/fit/<id>.fit         archivos .FIT originales tal como salen del reloj (fuente de verdad)
raw/actividades/<id>.json  resumen de cada actividad según Garmin Connect (nombre, tipo, etc.)
raw/dias/AAAA-MM-DD/     respuesta cruda de Garmin por día: FC continua, estrés, Body Battery,
                         sueño por fases, HRV, SpO2, respiración, pasos, pisos, preparación, etc.
data/
  actividades.csv        resumen por actividad (km, ritmo, FC, minutos por zona)
  dias.csv               resumen por día (sueño, HRV, FC en reposo, pasos, VO2max)
  dias_detalle.csv       ~45 métricas por día sacadas de raw/dias (estrés, Body Battery, calorías,
                         minutos de intensidad, fases de sueño, respiración, carga, preparación...)
  dias/AAAA-MM-DD.json   series del día listas para graficar (minutos desde las 00:00 de Lima)
  hoy.csv                estado del día (preparación, recuperación, carga, zonas)
  predicciones.csv       tiempos predichos por Garmin
  consejo.json           recomendación del día
  meta.json              fecha de la última actualización
  analisis/<id>.json     análisis del entrenador de cada carrera (lo escribe Claude)
  tendencia.json         evolución a largo plazo (lo escribe Claude en cada revisión del plan)
  plan/plan.json         plan de maratón semana a semana (lo revisa Claude solo en las fechas de revisión)
  historial/
    estado_diario.csv    una fila por día con preparación, carga, zonas y predicciones (lo escribe Claude)
    consejos.json        todas las recomendaciones diarias de Claude
  actividades/
    indice.csv           lista de actividades con .FIT procesado
    <id>.csv             un registro por segundo: lat, lon, distancia, velocidad, ritmo, FC,
                         cadencia, altitud, potencia, oscilación y ratio vertical, contacto
                         con el suelo, longitud de zancada, temperatura, condición de rendimiento
    <id>_vueltas.csv     vueltas (laps)
    <id>_km.csv          parciales por kilómetro
    <id>_series.csv      series de fuerza (reps, peso, ejercicio)
    <id>_sesion.json     todos los campos del resumen de la sesión del .FIT
scripts/
  procesar_fit.py        regenera data/actividades/ a partir de raw/fit/
  procesar_dias.py       regenera data/dias/ y data/dias_detalle.csv a partir de raw/dias/
  generar_tablas.py      genera actividades.csv, dias.csv, hoy.csv, predicciones.csv y el historial
                         a partir de raw/ (lo único que no genera es consejo.json: eso lo escribe Claude)
  descargar_garmin.py    baja de Garmin Connect los días completos y los .FIT nuevos (corre en la PC)
```

## Para tus algoritmos

```python
import pandas as pd
act = pd.read_csv("data/actividades/25050170539.csv")
dias = pd.read_csv("data/dias_detalle.csv", parse_dates=["fecha"])
fc_dia = pd.read_json("raw/dias/2026-11-12/fc.json", typ="series")  # crudo de Garmin
```

Los .FIT de `raw/fit/` tienen todo lo que grabó el reloj (también mensajes que el
script todavía no extrae). Para leerlos completos: `fitparse.FitFile("raw/fit/<id>.fit")`.

Si cambias `scripts/procesar_fit.py`, vuelve a correrlo para regenerar todas las tablas:
`pip install fitparse && python scripts/procesar_fit.py`

## Descarga automática (en la PC)

Una vez:
```bash
git clone https://github.com/davidrdcr/running ~/proyectos/running
~/miniconda3/bin/conda create -y -n garmin python=3.12
~/miniconda3/envs/garmin/bin/pip install garminconnect fitparse
~/miniconda3/envs/garmin/bin/python ~/proyectos/running/scripts/descargar_garmin.py --push
```

Para que corra solo dos veces al día (`crontab -e`):
```
15 9,22 * * * cd ~/proyectos/running && ~/miniconda3/envs/garmin/bin/python scripts/descargar_garmin.py --push >> ~/datasets/garmin/descarga.log 2>&1
```
