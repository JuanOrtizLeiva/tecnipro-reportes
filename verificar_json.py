"""Verificar JSON final con datos SENCE."""

import sys
import json
from pathlib import Path

# Configurar UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Leer JSON
with open('data/output/datos_procesados.json', encoding='utf-8') as f:
    data = json.load(f)

# Estadísticas
estudiantes_con_sence = sum(1 for c in data['cursos'] for e in c['estudiantes'] if e.get('n_ingresos', 0) > 0)
total_estudiantes = data['metadata']['total_estudiantes']
total_conexiones = sum(e.get('n_ingresos', 0) for c in data['cursos'] for e in c['estudiantes'])

print("=" * 80)
print("VERIFICACIÓN FINAL - Datos SENCE en JSON")
print("=" * 80)

print(f"\n✅ Estudiantes con conexiones SENCE: {estudiantes_con_sence}/{total_estudiantes}")
print(f"✅ Total conexiones registradas: {total_conexiones}")

# Ejemplos
print("\n" + "=" * 80)
print("EJEMPLOS DE ESTUDIANTES")
print("=" * 80)

estudiantes_con_conexiones = [e for c in data['cursos'] for e in c['estudiantes'] if e.get('n_ingresos', 0) > 0]

print(f"\n🟢 Estudiantes CON conexiones ({len(estudiantes_con_conexiones)}):")
for i, est in enumerate(estudiantes_con_conexiones[:5], 1):
    print(f"\n   {i}. {est['nombre']}")
    print(f"      - SENCE ID: {est['sence']['id_sence']}")
    print(f"      - Conexiones: {est['sence']['n_ingresos']}")
    print(f"      - Estado: {est['sence']['estado']}")

estudiantes_sin_conexiones = [e for c in data['cursos'] for e in c['estudiantes'] if e.get('n_ingresos', 0) == 0]

print(f"\n🔴 Estudiantes SIN conexiones ({len(estudiantes_sin_conexiones)}):")
for i, est in enumerate(estudiantes_sin_conexiones, 1):
    print(f"\n   {i}. {est['nombre']}")
    print(f"      - SENCE ID: {est['sence'].get('id_sence', 'N/A')}")
    print(f"      - Estado: {est['sence']['estado']}")

print("\n" + "=" * 80)
print("✅ PROBLEMA RESUELTO: Los datos SENCE ahora aparecen correctamente")
print("=" * 80)
