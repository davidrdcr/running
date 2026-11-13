"""Convierte los .FIT originales de raw/fit/ en tablas para el dashboard y para análisis.

Uso:  python scripts/procesar_fit.py            (procesa todos los .fit de raw/fit/)

Salidas por actividad, en data/actividades/:
  <id>.csv            una fila por registro del reloj (normalmente 1 por segundo)
  <id>_vueltas.csv    una fila por vuelta (lap)
  <id>_series.csv     series de fuerza (repeticiones, peso, ejercicio), si las hay
  <id>_sesion.json    todos los campos del mensaje "session" del FIT (resumen completo)
Y un índice: data/actividades/indice.csv
"""
import csv
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fitparse import FitFile

CATEGORIAS = ["press de banca", "pantorrillas", "cardio", "cargada", "chop", "core", "abdominales (crunch)", "curl", "peso muerto", "aperturas", "elevación de cadera", "estabilidad de cadera", "swing", "hiperextensión", "elevaciones laterales", "curl femoral", "elevación de piernas", "zancadas", "levantamiento olímpico", "plancha", "pliometría", "dominadas", "flexiones", "remo", "press de hombros", "estabilidad de hombros", "encogimientos", "abdominales (sit-up)", "sentadillas", "cuerpo completo", "extensión de tríceps", "calentamiento", "carrera"]

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "raw" / "fit"
SALIDA = RAIZ / "data" / "actividades"
LIMA = timezone(timedelta(hours=-5))
SEMI = 180 / 2**31

COLUMNAS = [
    "seg", "hora", "lat", "lon", "distancia_m", "velocidad_m_s", "ritmo_seg_km", "fc",
    "cadencia_spm", "altitud_m", "potencia_w", "oscilacion_vertical_mm", "ratio_vertical",
    "contacto_suelo_ms", "balance_contacto", "longitud_zancada_mm", "temperatura_c",
    "respiracion_rpm", "desempeno",
]


def limpio(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    if isinstance(v, (tuple, list)):
        return [limpio(x) for x in v]
    if isinstance(v, bytes):
        return v.hex()
    return v


def r(v, n=1):
    return "" if v is None else round(v, n)


def procesar(ruta: Path):
    act_id = ruta.stem
    fit = FitFile(str(ruta))
    filas, vueltas, series, sesion, deporte = [], [], [], {}, {}
    t0 = None
    for msg in fit.get_messages():
        d = {f.name: f.value for f in msg.fields if f.value is not None}
        if msg.name == "record":
            ts = d.get("timestamp")
            if ts is None:
                continue
            ts = ts.replace(tzinfo=timezone.utc)
            t0 = t0 or ts
            lat = d.get("position_lat")
            lon = d.get("position_long")
            vel = d.get("enhanced_speed", d.get("speed"))
            cad = d.get("cadence")
            if cad is not None:
                cad = cad * 2 + (d.get("fractional_cadence") or 0) * 2
            filas.append({
                "seg": int((ts - t0).total_seconds()),
                "hora": ts.astimezone(LIMA).strftime("%H:%M:%S"),
                "lat": r(lat * SEMI if isinstance(lat, int) else None, 6),
                "lon": r(lon * SEMI if isinstance(lon, int) else None, 6),
                "distancia_m": r(d.get("distance"), 1),
                "velocidad_m_s": r(vel, 3),
                "ritmo_seg_km": r(1000 / vel if vel and vel > 0.5 else None, 0),
                "fc": r(d.get("heart_rate"), 0),
                "cadencia_spm": r(cad, 0),
                "altitud_m": r(d.get("enhanced_altitude", d.get("altitude")), 1),
                "potencia_w": r(d.get("power"), 0),
                "oscilacion_vertical_mm": r(d.get("vertical_oscillation"), 1),
                "ratio_vertical": r(d.get("vertical_ratio"), 2),
                "contacto_suelo_ms": r(d.get("stance_time"), 0),
                "balance_contacto": r(d.get("stance_time_balance"), 1),
                "longitud_zancada_mm": r(d.get("step_length"), 0),
                "temperatura_c": r(d.get("temperature"), 0),
                "respiracion_rpm": r(d.get("enhanced_respiration_rate", d.get("respiration_rate")), 1),
                "desempeno": r(d.get("performance_condition", d.get("unknown_90")), 0) if isinstance(d.get("performance_condition", d.get("unknown_90")), (int, float)) else "",
            })
        elif msg.name == "lap":
            dist = d.get("total_distance")
            tiempo = d.get("total_timer_time")
            vueltas.append({
                "vuelta": len(vueltas) + 1,
                "inicio": d["start_time"].replace(tzinfo=timezone.utc).astimezone(LIMA).strftime("%H:%M:%S") if d.get("start_time") else "",
                "distancia_m": r(dist, 1),
                "tiempo_s": r(tiempo, 1),
                "ritmo_seg_km": r(tiempo / dist * 1000 if dist and tiempo else None, 0),
                "fc_prom": r(d.get("avg_heart_rate"), 0),
                "fc_max": r(d.get("max_heart_rate"), 0),
                "cadencia_spm": r((d.get("avg_running_cadence") or d.get("avg_cadence") or 0) * 2 + (d.get("avg_fractional_cadence") or 0) * 2 or None, 0),
                "potencia_w": r(d.get("avg_power"), 0),
                "desnivel_pos_m": r(d.get("total_ascent"), 0),
                "desnivel_neg_m": r(d.get("total_descent"), 0),
                "calorias": r(d.get("total_calories"), 0),
            })
        elif msg.name == "set":
            cat = d.get("category")
            cat = cat[0] if isinstance(cat, tuple) else cat
            ini = d.get("start_time")
            series.append({
                "serie": len(series) + 1,
                "tipo": "activa" if d.get("set_type") == "active" else "descanso",
                "inicio": ini.replace(tzinfo=timezone.utc).astimezone(LIMA).strftime("%H:%M:%S") if ini else "",
                "duracion_s": r(d.get("duration"), 1),
                "repeticiones": d.get("repetitions") if d.get("set_type") == "active" else "",
                "peso_kg": r(d.get("weight"), 1) if d.get("set_type") == "active" else "",
                "ejercicio": (CATEGORIAS[cat] if isinstance(cat, int) and cat < len(CATEGORIAS) else "sin identificar") if d.get("set_type") == "active" else "",
                "codigo_categoria": cat if isinstance(cat, int) else "",
            })
        elif msg.name == "session":
            sesion = {k: limpio(v) for k, v in d.items()}
        elif msg.name == "sport":
            deporte = {k: limpio(v) for k, v in d.items()}

    SALIDA.mkdir(parents=True, exist_ok=True)
    # Quita columnas que el reloj no registró en esta actividad
    usadas = [c for c in COLUMNAS if any(f[c] != "" and f[c] is not None for f in filas)]
    with open(SALIDA / f"{act_id}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=usadas, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    if vueltas:
        with open(SALIDA / f"{act_id}_vueltas.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(vueltas[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(vueltas)
    if series:
        with open(SALIDA / f"{act_id}_series.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(series[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(series)
    sesion["_deporte"] = deporte
    (SALIDA / f"{act_id}_sesion.json").write_text(json.dumps(sesion, ensure_ascii=False, indent=1))

    inicio = sesion.get("start_time")
    return {
        "id": act_id,
        "inicio": datetime.fromisoformat(inicio).astimezone(LIMA).strftime("%Y-%m-%d %H:%M") if inicio else "",
        "deporte": deporte.get("sport") or sesion.get("sport") or "",
        "registros": len(filas),
        "vueltas": len(vueltas),
        "series": len(series),
        "gps": int(any(f["lat"] != "" for f in filas)),
        "columnas": "|".join(usadas),
    }


def main():
    fits = sorted(RAW.glob("*.fit"))
    if not fits:
        sys.exit("No hay archivos en raw/fit/")
    indice = [procesar(f) for f in fits]
    indice.sort(key=lambda x: x["inicio"])
    with open(SALIDA / "indice.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(indice[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(indice)
    for i in indice:
        print(f'{i["id"]}  {i["inicio"]}  {i["deporte"]:<10} {i["registros"]:>5} registros  gps={i["gps"]}')


if __name__ == "__main__":
    main()
