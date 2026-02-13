"""Test rápido para verificar extracción de evaluaciones."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.ingest import moodle_api_client as api
from config import settings

print("=" * 60)
print("TEST: Extracción de evaluaciones")
print("=" * 60)

# Obtener primer curso
courses = api.get_courses(settings.MOODLE_CATEGORY_IDS)
if not courses:
    print("❌ No hay cursos")
    sys.exit(1)

curso = courses[0]
print(f"\n📚 Curso: {curso['fullname']} (ID: {curso['id']})")

# Obtener grades
print(f"\n🔍 Obteniendo grades...")
grades = api.get_grades(curso['id'])

print(f"\n✅ Grades obtenidos para {len(grades)} usuarios\n")

# Mostrar primeros 5 estudiantes
for idx, (userid, grade_data) in enumerate(list(grades.items())[:5], 1):
    print(f"[{idx}] Usuario {userid}")
    print(f"    Nota final: {grade_data.get('nota_final', 'N/A')}")
    print(f"    Evaluaciones: {grade_data['resumen_evaluaciones']}")
    print(f"    Promedio evaluadas: {grade_data.get('promedio_evaluadas', 'N/A')}")
    print()

# Verificar si hay estudiantes con evaluaciones
con_evals = sum(1 for g in grades.values() if g['total_evaluaciones'] > 0)
print(f"\n📊 Resumen:")
print(f"   Total usuarios: {len(grades)}")
print(f"   Con evaluaciones (>0): {con_evals}")
print(f"   Sin evaluaciones (0): {len(grades) - con_evals}")

if con_evals == 0:
    print("\n⚠️  ADVERTENCIA: Ningún usuario tiene evaluaciones!")
    print("   Esto puede indicar:")
    print("   - El curso no tiene actividades evaluables configuradas")
    print("   - Problema con completion tracking en Moodle")
    print("   - Error en la extracción de gradeitems")
