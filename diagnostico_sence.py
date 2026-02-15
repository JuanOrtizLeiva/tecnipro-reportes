"""Script de diagnóstico: verifica lectura de datos SENCE y merge con Moodle."""

import sys
from pathlib import Path

# Configurar UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from src.ingest.sence_reader import leer_sence

# Crear Excel de diagnóstico
output_path = Path.home() / "Downloads" / "diagnostico_sence.xlsx"

print("=" * 60)
print("DIAGNÓSTICO SENCE - Verificación de datos")
print("=" * 60)

# ── 1. Leer datos SENCE ──────────────────────────────────
print("\n[1/4] Leyendo datos SENCE...")
df_sence = leer_sence()

if df_sence.empty:
    print("⚠️  No se encontraron datos SENCE")
else:
    print(f"✅ SENCE: {len(df_sence)} registros")
    print(f"   - IDs SENCE únicos: {df_sence['IDSence'].nunique()}")
    print(f"   - RUTs únicos: {df_sence['IDUser'].nunique()}")
    print(f"   - Total conexiones: {df_sence['N_Ingresos'].sum()}")

# ── 2. Leer datos Moodle ─────────────────────────────────
print("\n[2/4] Leyendo datos Moodle...")

if settings.DATA_SOURCE == "api":
    print("   Modo API: leyendo desde Moodle API")
    from src.ingest.moodle_api_reader import leer_datos_moodle
    df_moodle = leer_datos_moodle()
else:
    print("   Modo CSV: leyendo desde Greporte + Dreporte")
    from src.ingest.dreporte_reader import leer_dreporte
    from src.ingest.greporte_reader import leer_greporte
    from src.transform.merger import merge_greporte_dreporte

    df_dreporte = leer_dreporte()
    df_greporte = leer_greporte()
    df_moodle = merge_greporte_dreporte(df_greporte, df_dreporte)

print(f"✅ Moodle: {len(df_moodle)} registros")
print(f"   - Cursos únicos: {df_moodle['nombre_corto'].nunique()}")
print(f"   - Estudiantes únicos: {df_moodle['Nombre completo Participante'].nunique()}")

# ── 3. Verificar columnas de cruce ───────────────────────
print("\n[3/4] Verificando columnas de cruce...")

# En Moodle: LLave se forma como RUT + IDSence
# Verificar si las columnas existen
if "LLave" not in df_moodle.columns:
    print("⚠️  Columna 'LLave' no existe en datos Moodle")
    if "IDUser" in df_moodle.columns and "IDSence" in df_moodle.columns:
        print("   Creando LLave = IDUser + IDSence")
        df_moodle["LLave"] = df_moodle["IDUser"] + df_moodle["IDSence"]
    else:
        print("   ERROR: No se pueden crear llaves de cruce")
        print(f"   Columnas disponibles: {list(df_moodle.columns)}")

# Mostrar ejemplos de llaves
print(f"\n   Ejemplos de LLaves SENCE:")
for llave in df_sence["LLave"].head(5):
    print(f"      {llave}")

print(f"\n   Ejemplos de LLaves Moodle:")
for llave in df_moodle["LLave"].head(5):
    print(f"      {llave}")

# ── 4. Hacer el merge y verificar resultados ─────────────
print("\n[4/4] Ejecutando merge...")

from src.transform.merger import merge_sence_into_dreporte

df_merged = merge_sence_into_dreporte(df_moodle.copy(), df_sence)

# Contar cuántos tienen conexiones
con_conexiones = (df_merged["N_Ingresos"] > 0).sum()
sin_conexiones = (df_merged["N_Ingresos"] == 0).sum()

print(f"\n✅ Merge completado:")
print(f"   - Total registros: {len(df_merged)}")
print(f"   - CON conexiones SENCE: {con_conexiones} ({con_conexiones/len(df_merged)*100:.1f}%)")
print(f"   - SIN conexiones SENCE: {sin_conexiones} ({sin_conexiones/len(df_merged)*100:.1f}%)")

# ── 5. Generar Excel de diagnóstico ──────────────────────
print(f"\n[5/5] Generando Excel de diagnóstico...")

with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    # Hoja 1: Datos SENCE consolidados
    df_sence_export = df_sence.copy()
    df_sence_export.to_excel(writer, sheet_name="SENCE_Raw", index=False)

    # Hoja 2: Datos Moodle con llaves
    df_moodle_export = df_moodle[["LLave", "IDUser", "IDSence", "nombre_corto", "Nombre completo Participante"]].copy()
    df_moodle_export.to_excel(writer, sheet_name="Moodle_Llaves", index=False)

    # Hoja 3: Resultado del merge
    df_merged_export = df_merged[[
        "nombre_corto",
        "Nombre completo Participante",
        "IDUser",
        "IDSence",
        "LLave",
        "N_Ingresos",
        "DJ"
    ]].copy()
    df_merged_export.to_excel(writer, sheet_name="Merge_Resultado", index=False)

    # Hoja 4: Análisis de matches
    # LLaves en SENCE pero no en Moodle
    llaves_sence = set(df_sence["LLave"])
    llaves_moodle = set(df_moodle["LLave"])

    solo_en_sence = llaves_sence - llaves_moodle
    solo_en_moodle = llaves_moodle - llaves_sence
    en_ambos = llaves_sence & llaves_moodle

    df_analisis = pd.DataFrame({
        "Métrica": [
            "LLaves en SENCE",
            "LLaves en Moodle",
            "LLaves en AMBOS (match exitoso)",
            "Solo en SENCE (no match)",
            "Solo en Moodle (no match)"
        ],
        "Cantidad": [
            len(llaves_sence),
            len(llaves_moodle),
            len(en_ambos),
            len(solo_en_sence),
            len(solo_en_moodle)
        ]
    })
    df_analisis.to_excel(writer, sheet_name="Analisis_Matches", index=False)

    # Hoja 5: Llaves que no hicieron match
    if solo_en_sence:
        df_no_match_sence = df_sence[df_sence["LLave"].isin(solo_en_sence)].copy()
        df_no_match_sence.to_excel(writer, sheet_name="No_Match_SENCE", index=False)

    if solo_en_moodle:
        df_no_match_moodle = df_moodle[df_moodle["LLave"].isin(solo_en_moodle)].copy()
        df_no_match_moodle.to_excel(writer, sheet_name="No_Match_Moodle", index=False)

print(f"\n✅ Excel generado: {output_path}")
print("\n" + "=" * 60)
print("RESUMEN DEL DIAGNÓSTICO")
print("=" * 60)
print(f"📊 Registros SENCE: {len(df_sence)}")
print(f"📊 Registros Moodle: {len(df_moodle)}")
print(f"📊 Matches exitosos: {len(en_ambos)} ({len(en_ambos)/len(llaves_moodle)*100:.1f}% de Moodle)")
print(f"📊 Estudiantes CON conexiones: {con_conexiones}")
print(f"📊 Estudiantes SIN conexiones: {sin_conexiones}")

if len(en_ambos) == 0:
    print("\n⚠️  PROBLEMA DETECTADO: NO HAY MATCHES")
    print("   Posibles causas:")
    print("   1. Formato de RUT diferente entre Moodle y SENCE")
    print("   2. ID SENCE no coincide entre Moodle y archivos")
    print("   3. Columna LLave no se está generando correctamente")
    print(f"\n   Revisa el Excel en: {output_path}")
    print("   Especialmente las hojas 'No_Match_SENCE' y 'No_Match_Moodle'")

print("\n" + "=" * 60)
