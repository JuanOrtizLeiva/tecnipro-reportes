"""Diagnóstico simple: comparar IDs SENCE descargados vs IDs en Moodle."""

import sys
from pathlib import Path

# Configurar UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from config import settings

print("=" * 70)
print("DIAGNÓSTICO: IDs SENCE - ¿Por qué no hay conexiones?")
print("=" * 70)

# ── 1. IDs SENCE descargados (archivos) ──────────────────
print("\n[1] IDs SENCE descargados (archivos en data/sence/):")
sence_path = Path("data/sence")
archivos_sence = sorted(sence_path.glob("*.csv"))
ids_descargados = [f.stem for f in archivos_sence]

print(f"   Total archivos: {len(ids_descargados)}")
for id_sence in ids_descargados:
    print(f"      - {id_sence}")

# ── 2. IDs SENCE en Moodle (grupos de estudiantes) ───────
print("\n[2] IDs SENCE en Moodle API (grupos de estudiantes):")

try:
    from src.ingest.moodle_api_client import get_all_sence_ids
    ids_moodle = get_all_sence_ids()

    print(f"   Total IDs en Moodle: {len(ids_moodle)}")
    for id_sence in ids_moodle:
        print(f"      - {id_sence}")

except Exception as e:
    print(f"   ERROR: {e}")
    ids_moodle = []

# ── 3. Comparación ────────────────────────────────────────
print("\n[3] Comparación:")

set_descargados = set(ids_descargados)
set_moodle = set(ids_moodle)

ids_match = set_descargados & set_moodle
ids_solo_descargados = set_descargados - set_moodle
ids_solo_moodle = set_moodle - set_descargados

print(f"\n   ✅ IDs que coinciden (MATCH): {len(ids_match)}")
if ids_match:
    for id_sence in sorted(ids_match):
        print(f"      - {id_sence}")

print(f"\n   ⚠️  IDs descargados pero NO en Moodle: {len(ids_solo_descargados)}")
if ids_solo_descargados:
    for id_sence in sorted(ids_solo_descargados):
        print(f"      - {id_sence} (archivo inútil)")

print(f"\n   ⚠️  IDs en Moodle pero NO descargados: {len(ids_solo_moodle)}")
if ids_solo_moodle:
    for id_sence in sorted(ids_solo_moodle):
        print(f"      - {id_sence} (FALTA descargar)")

# ── 4. Diagnóstico ────────────────────────────────────────
print("\n" + "=" * 70)
print("DIAGNÓSTICO FINAL")
print("=" * 70)

if len(ids_match) == 0:
    print("\n❌ PROBLEMA CRÍTICO: NO HAY MATCHES")
    print("\n   El scraper está descargando IDs SENCE que NO corresponden")
    print("   a los cursos actuales en Moodle.")
    print("\n   SOLUCIÓN:")
    print("   1. El orchestrator debe obtener IDs desde Moodle API")
    print("      (función get_all_sence_ids())")
    print("   2. Luego descargar SOLO esos IDs desde SENCE")
    print(f"\n   IDs que DEBERÍAN descargarse: {sorted(ids_solo_moodle)}")

elif len(ids_solo_moodle) > 0:
    print(f"\n⚠️  PARCIALMENTE CORRECTO: {len(ids_match)} matches")
    print(f"\n   Faltan descargar {len(ids_solo_moodle)} IDs:")
    for id_sence in sorted(ids_solo_moodle):
        print(f"      - {id_sence}")

else:
    print("\n✅ CORRECTO: Todos los IDs coinciden")
    print(f"\n   {len(ids_match)} archivos SENCE corresponden a cursos activos")

print("\n" + "=" * 70)

# ── 5. Generar Excel simplificado ────────────────────────
print("\n[4] Generando Excel de diagnóstico...")

from src.ingest.sence_reader import leer_sence

df_sence = leer_sence()

if settings.DATA_SOURCE == "api":
    from src.ingest.moodle_api_reader import leer_datos_moodle
    df_moodle = leer_datos_moodle()
else:
    from src.ingest.dreporte_reader import leer_dreporte
    from src.ingest.greporte_reader import leer_greporte
    from src.transform.merger import merge_greporte_dreporte

    df_dreporte = leer_dreporte()
    df_greporte = leer_greporte()
    df_moodle = merge_greporte_dreporte(df_greporte, df_dreporte)

output_path = Path.home() / "Downloads" / "diagnostico_sence.xlsx"

with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    # Hoja 1: IDs descargados vs IDs en Moodle
    df_comparacion = pd.DataFrame({
        "ID_SENCE": sorted(set_descargados | set_moodle),
    })
    df_comparacion["Descargado"] = df_comparacion["ID_SENCE"].isin(set_descargados)
    df_comparacion["En_Moodle"] = df_comparacion["ID_SENCE"].isin(set_moodle)
    df_comparacion["Match"] = df_comparacion["Descargado"] & df_comparacion["En_Moodle"]
    df_comparacion.to_excel(writer, sheet_name="Comparacion_IDs", index=False)

    # Hoja 2: Datos SENCE raw
    df_sence.to_excel(writer, sheet_name="SENCE_Raw", index=False)

    # Hoja 3: Resumen por ID SENCE
    df_resumen = df_sence.groupby("IDSence").agg({
        "IDUser": "count",
        "N_Ingresos": "sum"
    }).reset_index()
    df_resumen.columns = ["ID_SENCE", "Estudiantes", "Total_Conexiones"]
    df_resumen["En_Moodle"] = df_resumen["ID_SENCE"].isin(set_moodle)
    df_resumen.to_excel(writer, sheet_name="Resumen_SENCE", index=False)

    # Hoja 4: Cursos Moodle
    if "IDSence" in df_moodle.columns:
        df_cursos = df_moodle[["IDSence", "nombre_corto"]].drop_duplicates()
    elif "ID SENCE" in df_moodle.columns:
        df_cursos = df_moodle[["ID SENCE", "nombre_corto"]].drop_duplicates()
        df_cursos.columns = ["IDSence", "nombre_corto"]
    else:
        df_cursos = pd.DataFrame({"Nota": ["Columna IDSence no encontrada"]})

    df_cursos.to_excel(writer, sheet_name="Cursos_Moodle", index=False)

print(f"✅ Excel generado: {output_path}")
print("\nRevisa las hojas:")
print("   - Comparacion_IDs: ¿Qué IDs coinciden?")
print("   - Resumen_SENCE: ¿Cuántas conexiones hay por ID?")
print("   - Cursos_Moodle: ¿Qué IDs SENCE tienen los cursos activos?")
