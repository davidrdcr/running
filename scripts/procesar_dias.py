"""Convierte los JSON crudos de raw/dias/ en archivos livianos para el dashboard y para análisis.

Uso:  python scripts/procesar_dias.py

Salidas:
  data/dias/AAAA-MM-DD.json   series del día listas para graficar (minutos desde las 00:00 de Lima)
  data/dias/indice.json       lista de días disponibles
  data/dias_detalle.csv       una fila por día con ~40 métricas (para tus algoritmos)

Convenciones de las series: cada punto es [minuto, valor], donde minuto = minutos desde la
medianoche (hora de Lima) del día. Puede ser negativo en el sueño (empezó el día anterior).
Garmin usa valores negativos como códigos (-1 sin reloj, -2 en actividad): se guardan como null.
"""
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "raw" / "dias"
SALIDA = RAIZ / "data" / "dias"
LIMA = timezone(timedelta(hours=-5))
FASES = {0: "profundo", 1: "ligero", 2: "rem", 3: "despierto"}


def leer(carpeta, nombre):
    p = carpeta / f"{nombre}.json"
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except json.JSONDecodeError:
        return None


def a_dt(v):
    """Acepta ms epoch o texto GMT ('2026-11-13T05:27:55.0') y devuelve datetime UTC."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=timezone.utc)


def minuto(v, medianoche):
    dt = a_dt(v)
    return None if dt is None else round((dt - medianoche).total_seconds() / 60, 1)


def valor(v):
    return None if v is None or (isinstance(v, (int, float)) and v < 0) else v


def serie(arr, medianoche, idx_val=1):
    out = []
    for fila in arr or []:
        if not fila or fila[0] is None:
            continue
        out.append([minuto(fila[0], medianoche), valor(fila[idx_val])])
    return out


def procesar(carpeta: Path):
    fecha = carpeta.name
    medianoche = datetime.fromisoformat(fecha).replace(tzinfo=LIMA).astimezone(timezone.utc)
    d = {"fecha": fecha}
    fila = {"fecha": fecha}

    fc = leer(carpeta, "fc")
    if fc:
        d["fc"] = serie(fc.get("heartRateValues"), medianoche)

    est = leer(carpeta, "estres")
    if est:
        d["estres"] = serie(est.get("stressValuesArray"), medianoche)
        d["body_battery"] = serie(est.get("bodyBatteryValuesArray"), medianoche, idx_val=2)

    resp = leer(carpeta, "respiracion")
    if resp:
        d["respiracion"] = serie(resp.get("respirationValuesArray"), medianoche)
        fila["resp_despierto"] = resp.get("avgWakingRespirationValue")
        fila["resp_sueno"] = resp.get("avgSleepRespirationValue")

    pasos = leer(carpeta, "pasos")
    if isinstance(pasos, list):
        d["pasos"] = [[minuto(p["startGMT"], medianoche), p.get("steps"), p.get("primaryActivityLevel")] for p in pasos]

    pisos = leer(carpeta, "pisos")
    if pisos and pisos.get("floorValuesArray"):
        d["pisos"] = [[minuto(f[0], medianoche), f[2], f[3]] for f in pisos["floorValuesArray"] if len(f) >= 4]

    s = leer(carpeta, "sueno")
    if s and s.get("dailySleepDTO", {}).get("sleepStartTimestampGMT"):
        dto = s["dailySleepDTO"]
        fases = []
        for lv in s.get("sleepLevels") or []:
            fases.append([minuto(lv["startGMT"], medianoche), minuto(lv["endGMT"], medianoche),
                          FASES.get(int(lv.get("activityLevel", -1)), "?")])
        d["sueno"] = {
            "inicio": minuto(dto["sleepStartTimestampGMT"], medianoche),
            "fin": minuto(dto["sleepEndTimestampGMT"], medianoche),
            "fases": fases,
            "fc": [[minuto(x["startGMT"], medianoche), valor(x["value"])] for x in s.get("sleepHeartRate") or []],
            "hrv": [[minuto(x["startGMT"], medianoche), valor(x["value"])] for x in s.get("hrvData") or []],
            "respiracion": [[minuto(x["startTimeGMT"], medianoche), valor(x["respirationValue"])] for x in s.get("wellnessEpochRespirationDataDTOList") or []],
            "estres": [[minuto(x["startGMT"], medianoche), valor(x["value"])] for x in s.get("sleepStress") or []],
            "body_battery": [[minuto(x["startGMT"], medianoche), valor(x["value"])] for x in s.get("sleepBodyBattery") or []],
            "movimiento": [[minuto(x["startGMT"], medianoche), round(x["activityLevel"], 2)] for x in s.get("sleepMovement") or []],
            "inquietud": [minuto(x["startGMT"], medianoche) for x in s.get("sleepRestlessMoments") or []],
        }
        sc = dto.get("sleepScores") or {}
        fila.update({
            "sueno_h": round((dto.get("sleepTimeSeconds") or 0) / 3600, 2),
            "siesta_h": round((dto.get("napTimeSeconds") or 0) / 3600, 2),
            "profundo_h": round((dto.get("deepSleepSeconds") or 0) / 3600, 2),
            "ligero_h": round((dto.get("lightSleepSeconds") or 0) / 3600, 2),
            "rem_h": round((dto.get("remSleepSeconds") or 0) / 3600, 2),
            "despierto_h": round((dto.get("awakeSleepSeconds") or 0) / 3600, 2),
            "despertares": dto.get("awakeCount"),
            "sueno_puntaje": (sc.get("overall") or {}).get("value"),
            "sueno_estres": dto.get("avgSleepStress"),
            "sueno_fc_prom": dto.get("avgHeartRate"),
            "inquietud": s.get("restlessMomentsCount"),
            "hrv_noche": s.get("avgOvernightHrv"),
            "hrv_estado": s.get("hrvStatus"),
            "bb_cambio_sueno": s.get("bodyBatteryChange"),
            "sueno_necesario_h": round(((dto.get("sleepNeed") or {}).get("actual") or 0) / 60, 2) or None,
        })
        d["sueno_resumen"] = {k: fila[k] for k in ("sueno_h", "profundo_h", "ligero_h", "rem_h", "despierto_h", "sueno_puntaje", "hrv_noche")}

    hrv = leer(carpeta, "hrv")
    if hrv and hrv.get("hrvSummary"):
        fila["hrv_semana"] = hrv["hrvSummary"].get("weeklyAvg")

    r = leer(carpeta, "resumen")
    if r:
        fila.update({
            "pasos": r.get("totalSteps"), "meta_pasos": r.get("dailyStepGoal"),
            "distancia_km": round((r.get("totalDistanceMeters") or 0) / 1000, 2),
            "kcal_total": r.get("totalKilocalories"), "kcal_activas": r.get("activeKilocalories"),
            "pisos_subidos": round(r.get("floorsAscended") or 0, 1),
            "min_moderados": r.get("moderateIntensityMinutes"), "min_vigorosos": r.get("vigorousIntensityMinutes"),
            "fc_min": r.get("minHeartRate"), "fc_max": r.get("maxHeartRate"), "fc_reposo": r.get("restingHeartRate"),
            "estres_prom": valor(r.get("averageStressLevel")), "estres_max": valor(r.get("maxStressLevel")),
            "estres_bajo_min": round((r.get("lowStressDuration") or 0) / 60), "estres_medio_min": round((r.get("mediumStressDuration") or 0) / 60),
            "estres_alto_min": round((r.get("highStressDuration") or 0) / 60), "descanso_min": round((r.get("restStressDuration") or 0) / 60),
            "bb_max": r.get("bodyBatteryHighestValue"), "bb_min": r.get("bodyBatteryLowestValue"),
            "bb_cargado": r.get("bodyBatteryChargedValue"), "bb_gastado": r.get("bodyBatteryDrainedValue"),
            "bb_al_despertar": r.get("bodyBatteryAtWakeTime"),
            "sedentario_h": round((r.get("sedentarySeconds") or 0) / 3600, 2),
            "activo_min": round(((r.get("activeSeconds") or 0) + (r.get("highlyActiveSeconds") or 0)) / 60),
            "spo2_prom": r.get("averageSpo2"),
        })
        d["resumen"] = {k: fila.get(k) for k in ("pasos", "meta_pasos", "kcal_total", "kcal_activas", "fc_min", "fc_max", "fc_reposo",
                                                   "estres_prom", "bb_max", "bb_min", "bb_cargado", "bb_gastado", "pisos_subidos",
                                                   "min_moderados", "min_vigorosos", "resp_despierto")}

    prep = leer(carpeta, "preparacion_manana") or {}
    if isinstance(prep, dict) and prep:
        fila["preparacion"] = prep.get("score")
    ee = leer(carpeta, "estado_entrenamiento") or {}
    if isinstance(ee, dict):
        lt = ((ee.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {})
        st = next(iter(lt.values()), {}) if lt else {}
        if st.get("calendarDate") == fecha:
            ac = st.get("acuteTrainingLoadDTO") or {}
            fila.update({"carga_aguda": ac.get("dailyTrainingLoadAcute"), "carga_cronica": ac.get("dailyTrainingLoadChronic"),
                         "acwr": ac.get("acwrPercent"), "estado_entrenamiento": st.get("trainingStatusFeedbackPhrase")})
        vo = ((ee.get("mostRecentVO2Max") or {}).get("generic") or {})
        if vo.get("calendarDate") == fecha:
            fila["vo2max"] = vo.get("vo2MaxPreciseValue") or vo.get("vo2MaxValue")

    eventos = leer(carpeta, "body_battery") or []
    if isinstance(eventos, list) and eventos:
        d["eventos_bb"] = [{"tipo": e.get("eventType"), "inicio": minuto(e.get("eventStartTimeGmt"), medianoche),
                            "min": round((e.get("durationInMilliseconds") or 0) / 60000), "impacto": e.get("bodyBatteryImpact")}
                           for e in eventos[0].get("bodyBatteryActivityEvent") or []]

    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / f"{fecha}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    return fila


def main():
    carpetas = sorted(p for p in RAW.iterdir() if p.is_dir())
    filas = [procesar(c) for c in carpetas]
    (SALIDA / "indice.json").write_text(json.dumps([c.name for c in carpetas]))
    columnas = []
    for f in filas:
        for k in f:
            if k not in columnas:
                columnas.append(k)
    with open(RAIZ / "data" / "dias_detalle.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas, lineterminator="\n")
        w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in columnas})
    print(f"{len(filas)} días procesados → data/dias/ y data/dias_detalle.csv")


if __name__ == "__main__":
    main()
