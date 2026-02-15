"""Debug: comparar LLaves de SENCE vs Moodle."""

import sys
from pathlib import Path

# Configurar UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from src.ingest.sence_reader import leer_sence
from src.ingest.moodle_api_reader import leer_datos_moodle

print("=" * 80)
print("DEBUG: Comparar LLaves SENCE vs Moodle")
print("=" * 80)

# Leer datos
df_sence = leer_sence()
df_moodle = leer_datos_moodle()

print(f"\n📊 SENCE: {len(df_sence)} registros")
print(f"📊 Moodle: {len(df_moodle)} registros")

# Verificar columnas
print(f"\nColumnas Moodle:")
for col in sorted(df_moodle.columns):
    print(f"   - {col}")

# Verificar si existe LLave en Moodle
if "LLave" not in df_moodle.columns:
    print("\n⚠️  Moodle NO tiene columna 'LLave'")

    # Verificar si tiene las columnas necesarias
    if "ID del Usuario" in df_moodle.columns and "ID SENCE" in df_moodle.columns:
        print("   Tiene 'ID del Usuario' y 'ID SENCE'")
        print("   Creando LLave...")

        # Convertir ID SENCE a string sin decimales
        id_sence_str = df_moodle["ID SENCE"].fillna("").astype(str)
        id_sence_str = id_sence_str.str.replace(".0", "", regex=False)

        df_moodle["LLave"] = df_moodle["ID del Usuario"] + id_sence_str
        print(f"   ✅ LLave creada")
    else:
        print("   ❌ No se pueden crear LLaves")

# Mostrar ejemplos de LLaves
print("\n" + "=" * 80)
print("EJEMPLOS DE LLAVES")
print("=" * 80)

print("\n[SENCE] Primeras 10 LLaves:")
for i, llave in enumerate(df_sence["LLave"].head(10), 1):
    print(f"   {i:2d}. {llave}")

print("\n[Moodle] Primeras 10 LLaves:")
for i, llave in enumerate(df_moodle["LLave"].head(10), 1):
    print(f"   {i:2d}. {llave}")

# Comparar
llaves_sence = set(df_sence["LLave"])
llaves_moodle = set(df_moodle["LLave"])

matches = llaves_sence & llaves_moodle
solo_sence = llaves_sence - llaves_moodle
solo_moodle = llaves_moodle - llaves_sence

print("\n" + "=" * 80)
print("ANÁLISIS DE MATCHES")
print("=" * 80)

print(f"\n✅ Matches: {len(matches)}")
if matches:
    for llave in sorted(matches):
        print(f"   - {llave}")

print(f"\n⚠️  Solo en SENCE (no en Moodle): {len(solo_sence)}")
if solo_sence:
    for llave in list(solo_sence)[:10]:
        print(f"   - {llave}")
    if len(solo_sence) > 10:
        print(f"   ... y {len(solo_sence) - 10} más")

print(f"\n⚠️  Solo en Moodle (no en SENCE): {len(solo_moodle)}")
if solo_moodle:
    for llave in list(solo_moodle)[:10]:
        print(f"   - {llave}")
    if len(solo_moodle) > 10:
        print(f"   ... y {len(solo_moodle) - 10} más")

# Si no hay matches, analizar por qué
if len(matches) == 0:
    print("\n" + "=" * 80)
    print("🔍 ANÁLISIS DETALLADO (SIN MATCHES)")
    print("=" * 80)

    # Comparar formatos
    if len(df_sence) > 0:
        ejemplo_sence = df_sence.iloc[0]
        print(f"\n📋 Ejemplo SENCE:")
        print(f"   LLave: '{ejemplo_sence['LLave']}'")
        print(f"   IDUser: '{ejemplo_sence['IDUser']}'")
        print(f"   IDSence: '{ejemplo_sence['IDSence']}'")
        print(f"   Longitud LLave: {len(ejemplo_sence['LLave'])}")

    if len(df_moodle) > 0:
        ejemplo_moodle = df_moodle.iloc[0]
        print(f"\n📋 Ejemplo Moodle:")
        print(f"   LLave: '{ejemplo_moodle['LLave']}'")
        if "ID del Usuario" in df_moodle.columns:
            print(f"   ID del Usuario: '{ejemplo_moodle['ID del Usuario']}'")
        if "ID SENCE" in df_moodle.columns:
            print(f"   ID SENCE: '{ejemplo_moodle['ID SENCE']}'")
        print(f"   Longitud LLave: {len(ejemplo_moodle['LLave'])}")

    # Analizar si hay un problema de formato
    print("\n🔍 Posibles problemas:")
    print("   1. ¿Formato de RUT diferente? (con/sin puntos, con/sin guión)")
    print("   2. ¿Mayúsculas/minúsculas?")
    print("   3. ¿Espacios en blanco?")
    print("   4. ¿ID SENCE como float vs string?")

print("\n" + "=" * 80)
