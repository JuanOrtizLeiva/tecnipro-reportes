"""Test del lector completo Moodle API."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.ingest.moodle_api_reader import leer_datos_moodle

print("=" * 60)
print("TEST: Lector Moodle API Reader")
print("=" * 60)

print("\nLeyendo datos desde Moodle API...")
print("(Esto puede tomar ~30 segundos con 138 cursos)")

try:
    df = leer_datos_moodle()

    print(f"\n✅ DataFrame generado exitosamente")
    print(f"   Filas totales: {len(df)}")
    print(f"   Cursos únicos: {df['nombre_corto'].nunique()}")
    print(f"   Columnas: {len(df.columns)}")

    print("\n📊 Primeras 5 filas:")
    print(df[["nombre_corto", "Nombre completo Participante", "Progreso del estudiante", "Calificación"]].head())

    print("\n📋 Columnas del DataFrame:")
    for col in df.columns:
        print(f"   - {col}")

    print("\n📈 Estadísticas:")
    print(f"   Estudiantes totales: {len(df[df['Nombre completo Participante'] != ''])}")
    print(f"   Cursos vacíos: {len(df[df['Nombre completo Participante'] == ''])}")
    print(f"   Progreso promedio: {df['Progreso del estudiante'].mean():.1f}%")

    # Verificar que las fechas están en formato español
    print("\n📅 Ejemplo de fechas:")
    fecha_inicio = df["Fecha de inicio del curso"].dropna().iloc[0]
    print(f"   Fecha inicio: {fecha_inicio}")

    if "de" in fecha_inicio and "," in fecha_inicio:
        print(f"   ✓ Formato español correcto")
    else:
        print(f"   ✗ Formato incorrecto (esperaba español)")

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ Test completado")
print("=" * 60)
