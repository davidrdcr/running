"""Descarga TODOS los datos de Garmin Connect (días completos + .FIT de actividades) al repo.

Pensado para correr en la PC de David, que ya tiene la sesión de Garmin guardada en
~/.garminconnect (la misma que usa el servidor MCP).

Uso:
  python scripts/descargar_garmin.py                  # desde el último día guardado hasta hoy
  python scripts/descargar_garmin.py --desde 2026-11-01
  python scripts/descargar_garmin.py --push           # además hace commit y push al repo

Guarda:
  raw/dias/AAAA-MM-DD/<fuente>.json   respuesta cruda de Garmin para cada fuente y día
  raw/fit/<id>.fit                    archivo original de cada actividad
y luego corre scripts/procesar_fit.py para regenerar las tablas de actividades.

Requisitos (una vez):  pip install garminconnect fitparse
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIAS = RAIZ / "raw" / "dias"
FIT = RAIZ / "raw" / "fit"
INICIO_POR_DEFECTO = date(2026, 11, 1)
PAUSA = 0.6  # segundos entre llamadas, para que Garmin no corte

# nombre del archivo -> (método de la librería, cómo llamarlo)
FUENTES = {
    "resumen":            ("get_stats",                       lambda f, d: f(d)),
    "fc":                 ("get_heart_rates",                 lambda f, d: f(d)),
    "estres":             ("get_stress_data",                 lambda f, d: f(d)),
    "body_battery":       ("get_body_battery",                lambda f, d: f(d, d)),
    "body_battery_eventos": ("get_body_battery_events",       lambda f, d: f(d)),
    "sueno":              ("get_sleep_data",                  lambda f, d: f(d)),
    "hrv":                ("get_hrv_data",                    lambda f, d: f(d)),
    "spo2":               ("get_spo2_data",                   lambda f, d: f(d)),
    "respiracion":        ("get_respiration_data",            lambda f, d: f(d)),
    "pasos":              ("get_steps_data",                  lambda f, d: f(d)),
    "pisos":              ("get_floors",                      lambda f, d: f(d)),
    "minutos_intensidad": ("get_intensity_minutes_data",      lambda f, d: f(d)),
    "preparacion":        ("get_training_readiness",          lambda f, d: f(d)),
    "preparacion_manana": ("get_morning_training_readiness",  lambda f, d: f(d)),
    "estado_entrenamiento": ("get_training_status",           lambda f, d: f(d)),
    "max_metrics":        ("get_max_metrics",                 lambda f, d: f(d)),
    "fc_reposo":          ("get_rhr_day",                     lambda f, d: f(d)),
    "hidratacion":        ("get_hydration_data",              lambda f, d: f(d)),
    "eventos":            ("get_all_day_events",              lambda f, d: f(d)),
    "tolerancia_carrera": ("get_running_tolerance",           lambda f, d: f(d, d)),
}


def conectar():
    from garminconnect import Garmin
    tokens = os.environ.get("GARMINTOKENS", os.path.expanduser("~/.garminconnect"))
    g = Garmin()
    g.login(tokens)
    return g


def ultimo_dia_guardado():
    if not DIAS.exists():
        return None
    fechas = sorted(p.name for p in DIAS.iterdir() if p.is_dir())
    return date.fromisoformat(fechas[-1]) if fechas else None


def bajar_dia(g, dia: date, forzar: bool):
    carpeta = DIAS / dia.isoformat()
    carpeta.mkdir(parents=True, exist_ok=True)
    d = dia.isoformat()
    ok, fallos = 0, []
    fuentes = dict(FUENTES)
    if dia == date.today():
        # Las predicciones de carrera solo existen "a hoy": se guardan en el día en que se bajan.
        fuentes["predicciones"] = ("get_race_predictions", lambda f, d: f())
    for nombre, (metodo, llamar) in fuentes.items():
        archivo = carpeta / f"{nombre}.json"
        if archivo.exists() and not forzar:
            continue
        f = getattr(g, metodo, None)
        if f is None:
            continue  # la versión instalada de garminconnect no tiene este método
        try:
            datos = llamar(f, d)
            if datos not in (None, {}, []):
                archivo.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")))
                ok += 1
        except Exception as e:  # noqa: BLE001
            fallos.append(f"{nombre}: {type(e).__name__}")
        time.sleep(PAUSA)
    return ok, fallos


def bajar_actividades(g, desde: date, hasta: date):
    FIT.mkdir(parents=True, exist_ok=True)
    nuevas, fallos = 0, []
    try:
        acts = g.get_activities_by_date(desde.isoformat(), hasta.isoformat())
    except Exception as e:  # noqa: BLE001
        return 0, [f"lista de actividades: {type(e).__name__}"]
    for a in acts:
        aid = a.get("activityId")
        destino = FIT / f"{aid}.fit"
        if not aid or destino.exists():
            continue
        try:
            datos = g.download_activity(aid, dl_fmt=g.ActivityDownloadFormat.ORIGINAL)
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                fit = next(n for n in z.namelist() if n.lower().endswith(".fit"))
                destino.write_bytes(z.read(fit))
            nuevas += 1
        except Exception as e:  # noqa: BLE001
            fallos.append(f"actividad {aid}: {type(e).__name__}")
        time.sleep(PAUSA)
    return nuevas, fallos


def git(*args):
    return subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=date.fromisoformat)
    ap.add_argument("--hasta", type=date.fromisoformat, default=date.today())
    ap.add_argument("--push", action="store_true", help="hacer commit y push al terminar")
    args = ap.parse_args()

    ultimo = ultimo_dia_guardado()
    # Siempre vuelve a bajar los 2 últimos días guardados: Garmin los sigue completando.
    desde = args.desde or (ultimo - timedelta(days=1) if ultimo else INICIO_POR_DEFECTO)
    hasta = args.hasta

    if args.push:
        git("pull", "--rebase", "--autostash")

    g = conectar()
    print(f"Descargando {desde} → {hasta}")
    dia = desde
    while dia <= hasta:
        forzar = ultimo is None or dia >= (ultimo - timedelta(days=1))
        ok, fallos = bajar_dia(g, dia, forzar)
        print(f"  {dia}: {ok} fuentes" + (f"  (fallaron: {', '.join(fallos)})" if fallos else ""))
        dia += timedelta(days=1)

    nuevas, fallos = bajar_actividades(g, desde - timedelta(days=3), hasta)
    print(f"Actividades nuevas: {nuevas}" + (f"  (fallaron: {', '.join(fallos)})" if fallos else ""))

    if any(FIT.glob("*.fit")):
        subprocess.run([sys.executable, str(RAIZ / "scripts" / "procesar_fit.py")], check=False)
    subprocess.run([sys.executable, str(RAIZ / "scripts" / "procesar_dias.py")], check=False)

    if args.push:
        git("add", "raw", "data/actividades", "data/dias", "data/dias_detalle.csv")
        if git("diff", "--cached", "--quiet").returncode != 0:
            git("commit", "-m", f"Datos de Garmin hasta {hasta}")
            r = git("push")
            print("Push:", "ok" if r.returncode == 0 else r.stderr.strip())
        else:
            print("Sin cambios que subir.")


if __name__ == "__main__":
    main()
