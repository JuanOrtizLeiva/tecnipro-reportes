"""Debug para ver estructura de gradeitems."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.ingest import moodle_api_client as api
from config import settings
import json

print("=" * 60)
print("DEBUG: Estructura de Grades")
print("=" * 60)

# Obtener primer curso
courses = api.get_courses(settings.MOODLE_CATEGORY_IDS)
if not courses:
    print("No hay cursos")
    sys.exit(1)

curso = courses[0]
print(f"\n📚 Curso: {curso['fullname']}")
print(f"   ID: {curso['id']}")

# Obtener grades
print(f"\n🔍 Obteniendo grades del curso {curso['id']}...")
grades_response = api.moodle_api_call("gradereport_user_get_grade_items", {"courseid": curso['id']})

print(f"\n📦 Estructura completa de la respuesta:")
print(json.dumps(grades_response, indent=2, ensure_ascii=False)[:2000])  # Primeros 2000 caracteres

# Analizar primer usuario
if 'usergrades' in grades_response and len(grades_response['usergrades']) > 0:
    usergrade = grades_response['usergrades'][0]
    print(f"\n👤 Primer usuario: {usergrade.get('userid')}")

    if 'gradeitems' in usergrade:
        print(f"\n📊 Total gradeitems: {len(usergrade['gradeitems'])}")

        for idx, item in enumerate(usergrade['gradeitems']):
            itemtype = item.get('itemtype', 'N/A')
            itemname = item.get('itemname', 'N/A')
            graderaw = item.get('graderaw', 'N/A')

            print(f"\n   [{idx+1}] {itemname}")
            print(f"       itemtype: {itemtype}")
            print(f"       graderaw: {graderaw}")
            print(f"       Todas las keys: {list(item.keys())}")
