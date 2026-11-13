"""Genera las tablas del dashboard a partir de los datos crudos (raw/dias, raw/fit, raw/actividades).

Uso:  python scripts/generar_tablas.py

Escribe (todo calculado, nada a mano):
  data/actividades.csv            una fila por actividad, con minutos en cada zona de FC
  data/dias.csv                   una fila por día: sueño, HRV, FC en reposo, pasos, VO2max, predicción
  data/hoy.csv                    estado del último día: preparación, recuperación, carga, zonas
  data/predicciones.csv           últimas predicciones de carrera
  data/historial/estado_diario.csv  hoy.csv + predicciones, una fila por día (se acumula)
  data/meta.json                  hora de la última actualización

No toca data/consejo.json ni data/historial/consejos.json: esos los escribe Claude.
"""
import csv
import json
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

from fitparse import FitFile

RAIZ = Path(__file__).resolve().parent.parent
DIAS = RAIZ / "raw" / "dias"
FIT = RAIZ / "raw" / "fit"
ACTS = RAIZ / "raw" / "actividades"
DATA = RAIZ / "data"
LIMA = timezone(timedelta(hours=-5))

COL_ACT = "id,fecha,hora,nombre,tipo,km,minutos,ritmo_seg_km,fc_prom,fc_max,calorias,z1_min,z2_min,z3_min,z4_min,z5_min".split(",")
COL_DIAS = "fecha,acostarse,levantarse,sueno_h,siesta_h,sueno_puntaje,profundo_h,ligero_h,rem_h,hrv_ms,fc_reposo,pasos,vo2max,maraton_seg".split(",")
COL_HOY = "fecha,preparacion,recuperacion_h,vo2max,carga_aguda,carga_optima_min,carga_optima_max,hrv_semana_ms,fc_reposo,body_battery_cargado,z2_desde,z2_hasta,z4_desde".split(",")
COL_EST = COL_HOY + ["pred_5k_seg", "pred_10k_seg", "pred_media_seg", "pred_maraton_seg"]
DIST = [("5K", 5, ("time5K", "5K")), ("10K", 10, ("time10K", "10K")),
        ("Media maratón", 21.0975, ("timeHalfMarathon", "half_marathon")), ("Maratón", 42.195, ("timeMarathon", "marathon"))]


def leer_json(p):
    try:
        return json.loads(Path(p).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def leer_csv(p):
    try:
        with open(p) as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []


def escribir_csv(p, columnas, filas):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in columnas})


def hhmm_gmt(v):
    if v is None:
        return None
    dt = datetime.fromtimestamp(v / 1000, timezone.utc) if isinstance(v, (int, float)) else datetime.fromisoformat(str(v)).replace(tzinfo=timezone.utc)
    return dt.astimezone(LIMA).strftime("%H:%M")


def r(v, n):
    return None if v is None else round(v, n)


# ---------- Actividades (desde los .FIT) ----------

def leer_fit(ruta):
    """Devuelve sesión, deporte y el time_in_zone de la sesión (mensaje FIT 216)."""
    sesion, deporte, zonas, limites = {}, {}, None, None
    for m in FitFile(str(ruta)).get_messages(["session", "sport", "unknown_216", "time_in_zone"]):
        d = {f.name: f.value for f in m.fields}
        if m.name == "session":
            sesion = d
        elif m.name == "sport":
            deporte = d
        else:
            ref = d.get("reference_mesg", d.get("unknown_0"))
            tiempos = d.get("time_in_hr_zone", d.get("unknown_2"))
            lim = d.get("hr_zone_high_boundary", d.get("unknown_6"))
            if ref in (18, "session") and tiempos:
                zonas = tiempos
                if lim and lim[0] is not None:
                    limites = lim
    return sesion, deporte, zonas, limites


def tabla_actividades():
    previas = {f["id"]: f for f in leer_csv(DATA / "actividades.csv")}
    filas, ultimas_zonas = [], None
    for ruta in sorted(FIT.glob("*.fit")):
        aid = ruta.stem
        try:
            s, dep, zonas, limites = leer_fit(ruta)
        except Exception as e:  # noqa: BLE001
            print(f"  no se pudo leer {ruta.name}: {e}")
            continue
        if not s.get("start_time"):
            continue
        inicio = s["start_time"].replace(tzinfo=timezone.utc).astimezone(LIMA)
        deporte, sub = str(s.get("sport") or dep.get("sport") or ""), str(s.get("sub_sport") or dep.get("sub_sport") or "")
        tipo = "carrera" if deporte == "running" else "fuerza" if "strength" in sub or deporte == "training" else deporte.lower()
        resumen = leer_json(ACTS / f"{aid}.json") or {}
        nombre = resumen.get("activityName") or previas.get(aid, {}).get("nombre") or dep.get("name") or tipo.capitalize()
        nombre = nombre.replace("Carrera", "").replace(",", " ").strip() or "Carrera"
        dist = s.get("total_distance") or 0
        tiempo = s.get("total_timer_time") or 0
        f = {"id": aid, "fecha": inicio.strftime("%Y-%m-%d"), "hora": inicio.strftime("%H:%M"), "nombre": nombre, "tipo": tipo,
             "km": r(dist / 1000, 2) if dist > 50 else None, "minutos": r(tiempo / 60, 1),
             "ritmo_seg_km": round(tiempo / (dist / 1000)) if dist > 50 and tiempo else None,
             "fc_prom": s.get("avg_heart_rate"), "fc_max": s.get("max_heart_rate"), "calorias": s.get("total_calories")}
        if tipo == "carrera" and zonas:
            for i in range(1, 6):
                f[f"z{i}_min"] = r((zonas[i] or 0) / 60000, 1)
            if limites:
                ultimas_zonas = (inicio, limites)
        filas.append(f)
    filas.sort(key=lambda x: (x["fecha"], x["hora"]))
    escribir_csv(DATA / "actividades.csv", COL_ACT, filas)
    return filas, ultimas_zonas


# ---------- Días ----------

def predicciones(fecha):
    p = leer_json(DIAS / fecha / "predicciones.json")
    if isinstance(p, list):
        p = p[0] if p else None
    if not isinstance(p, dict):
        return None
    out = {}
    for nombre, _, claves in DIST:
        v = next((p[k] for k in claves if p.get(k) is not None), None)
        if isinstance(v, dict):
            v = v.get("time_seconds")
        out[nombre] = int(v) if v else None
    return out if any(out.values()) else None


def estado(fecha):
    ee = leer_json(DIAS / fecha / "estado_entrenamiento.json") or {}
    lt = ((ee.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {})
    st = next(iter(lt.values()), {}) if lt else {}
    ac = st.get("acuteTrainingLoadDTO") or {} if st.get("calendarDate") == fecha else {}
    vo = (ee.get("mostRecentVO2Max") or {}).get("generic") or {}
    mm = leer_json(DIAS / fecha / "max_metrics.json")
    mm = ((mm[0] if isinstance(mm, list) and mm else mm) or {}).get("generic") or {}
    vo2 = None
    for fuente in (mm, vo):
        if fuente.get("calendarDate") == fecha and (fuente.get("vo2MaxPreciseValue") or fuente.get("vo2MaxValue")):
            vo2 = fuente.get("vo2MaxPreciseValue") or fuente.get("vo2MaxValue")
            break
    return ac, vo2, vo.get("vo2MaxPreciseValue") or vo.get("vo2MaxValue") or vo2


def tabla_dias():
    hoy = date.today().isoformat()
    hist = {f["fecha"]: f for f in leer_csv(DATA / "historial" / "estado_diario.csv")}
    filas = []
    for carpeta in sorted(p for p in DIAS.iterdir() if p.is_dir()):
        fecha = carpeta.name
        s = leer_json(carpeta / "sueno.json") or {}
        dto = s.get("dailySleepDTO") or {}
        res = leer_json(carpeta / "resumen.json") or {}
        _, vo2, _ = estado(fecha)
        pred = predicciones(fecha) or {}
        if not pred.get("Maratón") and hist.get(fecha, {}).get("pred_maraton_seg"):
            pred["Maratón"] = int(hist[fecha]["pred_maraton_seg"])
        f = {"fecha": fecha}
        if dto.get("sleepStartTimestampGMT"):
            f.update({
                "acostarse": hhmm_gmt(dto["sleepStartTimestampGMT"]), "levantarse": hhmm_gmt(dto["sleepEndTimestampGMT"]),
                "sueno_h": r((dto.get("sleepTimeSeconds") or 0) / 3600, 2), "siesta_h": r((dto.get("napTimeSeconds") or 0) / 3600, 2),
                "sueno_puntaje": ((dto.get("sleepScores") or {}).get("overall") or {}).get("value"),
                "profundo_h": r((dto.get("deepSleepSeconds") or 0) / 3600, 2), "ligero_h": r((dto.get("lightSleepSeconds") or 0) / 3600, 2),
                "rem_h": r((dto.get("remSleepSeconds") or 0) / 3600, 2),
                "hrv_ms": round(s["avgOvernightHrv"]) if s.get("avgOvernightHrv") is not None else None, "fc_reposo": s.get("restingHeartRate") or res.get("restingHeartRate"),
            })
        if fecha < hoy and res.get("totalSteps") is not None:
            f["pasos"] = res["totalSteps"]
        f["vo2max"] = vo2
        f["maraton_seg"] = pred.get("Maratón")
        # Días sin sueño y casi sin pasos (reloj sin usar) no aportan
        if "sueno_h" not in f and (f.get("pasos") or 0) < 500:
            continue
        filas.append(f)
    # Lo que el crudo no tenga se conserva de la tabla anterior; los días viejos no se pierden
    previas = {f["fecha"]: f for f in leer_csv(DATA / "dias.csv")}
    por_fecha = {f["fecha"]: f for f in filas}
    for fecha, vieja in previas.items():
        if fecha not in por_fecha:
            filas.append(vieja)
            continue
        nueva = por_fecha[fecha]
        for k in COL_DIAS:
            if nueva.get(k) in (None, "") and vieja.get(k) not in (None, ""):
                nueva[k] = vieja[k]
    filas.sort(key=lambda x: x["fecha"])
    escribir_csv(DATA / "dias.csv", COL_DIAS, filas)
    return filas


# ---------- Hoy, predicciones e historial ----------

def fila_estado(fecha, limites, previo):
    carpeta = DIAS / fecha
    prep = leer_json(carpeta / "preparacion_manana.json")
    if isinstance(prep, list):
        prep = prep[0] if prep else None
    prep = prep or {}
    ac, _, vo2_ultimo = estado(fecha)
    hrv = (leer_json(carpeta / "hrv.json") or {}).get("hrvSummary") or {}
    bb = leer_json(carpeta / "body_battery.json") or []
    res = leer_json(carpeta / "resumen.json") or {}
    s = leer_json(carpeta / "sueno.json") or {}
    f = {"fecha": fecha,
         "preparacion": prep.get("score"),
         "recuperacion_h": r(prep["recoveryTime"] / 60, 1) if prep.get("recoveryTime") is not None else None,
         "vo2max": vo2_ultimo,
         "carga_aguda": ac.get("dailyTrainingLoadAcute"),
         "carga_optima_min": round(ac["minTrainingLoadChronic"]) if ac.get("minTrainingLoadChronic") is not None else None,
         "carga_optima_max": round(ac["maxTrainingLoadChronic"]) if ac.get("maxTrainingLoadChronic") is not None else None,
         "hrv_semana_ms": hrv.get("weeklyAvg") or prep.get("hrvWeeklyAverage"),
         "fc_reposo": s.get("restingHeartRate") or res.get("restingHeartRate"),
         "body_battery_cargado": (bb[0].get("charged") if isinstance(bb, list) and bb else None)}
    if limites:
        f.update({"z2_desde": limites[1], "z2_hasta": limites[2] - 1, "z4_desde": limites[3]})
    elif previo:
        f.update({k: previo.get(k) for k in ("z2_desde", "z2_hasta", "z4_desde")})
    return f


def main():
    acts, ultimas_zonas = tabla_actividades()
    dias = tabla_dias()
    fechas = sorted(p.name for p in DIAS.iterdir() if p.is_dir())
    previo_hoy = (leer_csv(DATA / "hoy.csv") or [{}])[0]
    limites = ultimas_zonas[1] if ultimas_zonas else None

    # Historial de estado: una fila por día con preparación (no se borra nada que ya estuviera)
    historial = {f["fecha"]: f for f in leer_csv(DATA / "historial" / "estado_diario.csv")}
    for fecha in fechas:
        f = fila_estado(fecha, limites, previo_hoy)
        if f["preparacion"] is None and f["carga_aguda"] is None:
            continue
        viejo = historial.get(fecha, {})
        pred = predicciones(fecha)
        f.update({"pred_5k_seg": (pred or {}).get("5K") or viejo.get("pred_5k_seg"),
                  "pred_10k_seg": (pred or {}).get("10K") or viejo.get("pred_10k_seg"),
                  "pred_media_seg": (pred or {}).get("Media maratón") or viejo.get("pred_media_seg"),
                  "pred_maraton_seg": (pred or {}).get("Maratón") or viejo.get("pred_maraton_seg")})
        # Lo que el crudo no tenga se conserva del historial previo
        historial[fecha] = {k: (f.get(k) if f.get(k) not in (None, "") else viejo.get(k)) for k in COL_EST}
    filas_hist = [historial[k] for k in sorted(historial)]
    escribir_csv(DATA / "historial" / "estado_diario.csv", COL_EST, filas_hist)

    # Hoy = último día con preparación o carga
    if filas_hist:
        escribir_csv(DATA / "hoy.csv", COL_HOY, [filas_hist[-1]])

    # Predicciones: las más recientes disponibles
    for fecha in reversed(fechas):
        pred = predicciones(fecha)
        if pred:
            filas = []
            for nombre, km, _ in DIST:
                seg = pred.get(nombre)
                if seg:
                    h, m, x = seg // 3600, seg % 3600 // 60, seg % 60
                    filas.append({"distancia": nombre, "tiempo": f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}",
                                  "segundos": seg, "ritmo_seg_km": round(seg / km)})
            escribir_csv(DATA / "predicciones.csv", ["distancia", "tiempo", "segundos", "ritmo_seg_km"], filas)
            break

    (DATA / "meta.json").write_text(json.dumps({"actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    print(f"Tablas: {len(acts)} actividades, {len(dias)} días, hoy = {filas_hist[-1]['fecha'] if filas_hist else '—'}")


if __name__ == "__main__":
    main()
