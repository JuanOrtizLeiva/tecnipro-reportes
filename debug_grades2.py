"""Debug para verificar estudiantes con notas."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.ingest import moodle_api_client as api
from config import settings

print("=" * 60)
print("DEBUG: Estudiantes con notas")
print("=" * 60)

# Obtener primer curso
courses = api.get_courses(settings.MOODLE_CATEGORY_IDS)
if not courses:
    print("No hay cursos")
    sys.exit(1)

curso = courses[0]
print(f"\n📚 Curso: {curso['fullname']} (ID: {curso['id']})")

# Obtener grades
grades_response = api.moodle_api_call("gradereport_user_get_grade_items", {"courseid": curso['id']})

usergrades = grades_response.get('usergrades', [])
print(f"\n📊 Total usuarios: {len(usergrades)}")

# Analizar cada usuario
for idx, usergrade in enumerate(usergrades, 1):
    userid = usergrade.get('userid')
    username = usergrade.get('userfullname')
    gradeitems = usergrade.get('gradeitems', [])

    # Contar evaluaciones
    total_evals = 0
    evals_rendidas = 0
    notas = []

    for item in gradeitems:
        itemtype = item.get('itemtype', '')

        if itemtype == 'course':
            nota_final = item.get('graderaw')
        elif itemtype not in ['course', 'category']:
            total_evals += 1
            graderaw = item.get('graderaw')
            if graderaw is not None:
                evals_rendidas += 1
                notas.append(graderaw)

    promedio = round(sum(notas) / len(notas), 1) if notas else None

    print(f"\n[{idx}] {username}")
    print(f"    Evaluaciones: {evals_rendidas}/{total_evals}")
    if promedio:
        print(f"    Promedio: {promedio}")
        print(f"    Notas: {notas}")

print(f"\n✅ Análisis completo")
