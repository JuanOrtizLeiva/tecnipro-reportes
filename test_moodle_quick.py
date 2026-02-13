"""Test rápido del cliente Moodle API."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.ingest import moodle_api_client as api
from config import settings

print("=" * 60)
print("TEST RÁPIDO: Moodle API Client")
print("=" * 60)

# Test 1: Categorías
print("\n1. Obteniendo categorías...")
try:
    categories = api.get_categories()
    print(f"   ✓ {len(categories)} categorías obtenidas")
    print(f"   Ejemplo: {list(categories.items())[:3]}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    sys.exit(1)

# Test 2: Cursos
print("\n2. Obteniendo cursos...")
try:
    courses = api.get_courses(settings.MOODLE_CATEGORY_IDS)
    print(f"   ✓ {len(courses)} cursos obtenidos")
    if courses:
        c = courses[0]
        print(f"   Ejemplo: {c.get('shortname')} - {c.get('fullname')[:50]}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    sys.exit(1)

# Test 3: Estudiantes de primer curso
if courses:
    print(f"\n3. Obteniendo estudiantes del curso {courses[0].get('shortname')}...")
    try:
        students = api.get_enrolled_users(courses[0]["id"])
        print(f"   ✓ {len(students)} estudiantes obtenidos")
        if students:
            s = students[0]
            print(f"   Ejemplo: {s.get('fullname')} ({s.get('email')})")
    except Exception as e:
        print(f"   ✗ Error: {e}")

# Test 4: Notas del primer curso
if courses:
    print(f"\n4. Obteniendo notas del curso {courses[0].get('shortname')}...")
    try:
        grades = api.get_grades(courses[0]["id"])
        print(f"   ✓ {len(grades)} notas obtenidas")
        # Mostrar primeras 3 notas
        for userid, grade in list(grades.items())[:3]:
            print(f"   Usuario {userid}: {grade}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

# Test 5: Progreso de primer estudiante
if courses and students:
    print(f"\n5. Obteniendo progreso del estudiante {students[0].get('fullname')}...")
    try:
        progreso = api.get_completion_status(courses[0]["id"], students[0]["id"])
        print(f"   ✓ Progreso: {progreso}%")
    except Exception as e:
        print(f"   ✗ Error: {e}")

print("\n" + "=" * 60)
print("✅ Todos los tests pasaron")
print("=" * 60)
