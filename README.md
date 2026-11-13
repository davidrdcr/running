# running

Dashboard de entrenamiento para maratón con datos de un Garmin Forerunner 570.
Página: https://davidrdcr.github.io/running/

## Estructura

```
index.html               dashboard principal
actividad.html           vista de cada actividad (mapa + datos segundo a segundo)
raw/fit/<id>.fit         archivos .FIT originales tal como salen del reloj (fuente de verdad)
data/
  actividades.csv        resumen por actividad (km, ritmo, FC, minutos por zona)
  dias.csv               resumen por día (sueño, HRV, FC en reposo, pasos, VO2max)
  hoy.csv                estado del día (preparación, recuperación, carga, zonas)
  predicciones.csv       tiempos predichos por Garmin
  consejo.json           recomendación del día
  meta.json              fecha de la última actualización
  actividades/
    indice.csv           lista de actividades con .FIT procesado
    <id>.csv             un registro por segundo: lat, lon, distancia, velocidad, ritmo, FC,
                         cadencia, altitud, potencia, oscilación y ratio vertical, contacto
                         con el suelo, longitud de zancada, temperatura, condición de rendimiento
    <id>_vueltas.csv     vueltas (laps)
    <id>_series.csv      series de fuerza (reps, peso, ejercicio)
    <id>_sesion.json     todos los campos del resumen de la sesión del .FIT
scripts/
  procesar_fit.py        regenera data/actividades/ a partir de raw/fit/
```

## Para tus algoritmos

```python
import pandas as pd
act = pd.read_csv("data/actividades/25050170539.csv")
dias = pd.read_csv("data/dias.csv", parse_dates=["fecha"])
```

Los .FIT de `raw/fit/` tienen todo lo que grabó el reloj (también mensajes que el
script todavía no extrae). Para leerlos completos: `fitparse.FitFile("raw/fit/<id>.fit")`.

Si cambias `scripts/procesar_fit.py`, vuelve a correrlo para regenerar todas las tablas:
`pip install fitparse && python scripts/procesar_fit.py`
