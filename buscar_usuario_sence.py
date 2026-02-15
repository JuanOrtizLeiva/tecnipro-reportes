"""Buscar usuario en archivos SENCE y verificar datos Moodle."""

import sys
from pathlib import Path

# Configurar UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import json

# Usuarios a investigar
usuarios = [
    {"nombre": "Margarita Victoria Suazo Rodríguez", "rut": "11912163-9", "id_sence": "6763149"},
    {"nombre": "Francis Margot Orellana Aguilera", "rut": "13950439-9", "id_sence": "6763150"},
]

print("=" * 80)
print("INVESTIGACIÓN: Usuarios con conexiones SENCE pero sin acceso Moodle")
print("=" * 80)

for usuario in usuarios:
    print(f"\n{'=' * 80}")
    print(f"USUARIO: {usuario['nombre']}")
    print(f"RUT: {usuario['rut']}")
    print(f"ID SENCE: {usuario['id_sence']}")
    print("=" * 80)

    # 1. Buscar en archivo SENCE
    archivo_sence = Path(f"data/sence/{usuario['id_sence']}.csv")
    print(f"\n[1] Buscando en archivo SENCE: {archivo_sence.name}")

    if archivo_sence.exists():
        try:
            # Leer como Excel (recordar que son .xlsx disfrazados de .csv)
            df = pd.read_excel(archivo_sence)
            print(f"   Total filas en archivo: {len(df)}")

            # Buscar RUT (sin guión y sin dígito verificador para hacer match flexible)
            rut_base = usuario['rut'].split('-')[0]  # "11912163"
            filas = df[df.iloc[:, 0].astype(str).str.contains(rut_base, na=False)]

            if len(filas) > 0:
                print(f"   ✅ ENCONTRADO: {len(filas)} registro(s)")
                print(f"\n   Datos en SENCE:")
                for idx, fila in filas.iterrows():
                    print(f"      - RUT: {fila.iloc[0]}")
                    print(f"      - Nombre: {fila.iloc[1]}")
                    if len(fila) > 2:
                        print(f"      - Columnas adicionales: {list(fila.iloc[2:])}")
            else:
                print(f"   ❌ NO ENCONTRADO en archivo SENCE")
        except Exception as e:
            print(f"   ⚠️  Error leyendo archivo: {e}")
    else:
        print(f"   ❌ Archivo no existe")

    # 2. Verificar datos en Moodle API (del JSON procesado)
    print(f"\n[2] Verificando datos en JSON procesado:")
    with open('data/output/datos_procesados.json', encoding='utf-8') as f:
        data = json.load(f)

    estudiante = None
    for curso in data['cursos']:
        for est in curso['estudiantes']:
            if est['id'] == usuario['rut']:
                estudiante = est
                break
        if estudiante:
            break

    if estudiante:
        print(f"   ✅ Encontrado en JSON")
        print(f"      - Último acceso: {estudiante.get('ultimo_acceso')}")
        print(f"      - Días sin acceso: {estudiante.get('dias_sin_acceso')}")
        print(f"      - Conexiones SENCE: {estudiante['sence']['n_ingresos']}")
        print(f"      - Progreso: {estudiante.get('progreso')}%")
        print(f"      - Calificación: {estudiante.get('calificacion')}")
    else:
        print(f"   ❌ No encontrado en JSON")

    # 3. Verificar en datos crudos de Moodle API
    print(f"\n[3] Consultando Moodle API directamente...")
    try:
        from src.ingest.moodle_api_client import get_enrolled_users

        # El curso tiene ID 190 (Excel) según el JSON
        usuarios_curso = get_enrolled_users(190)
        usuario_moodle = None

        for u in usuarios_curso:
            username = str(u.get('username', '')).strip().lower()
            if rut_base in username or usuario['rut'] in username:
                usuario_moodle = u
                break

        if usuario_moodle:
            print(f"   ✅ Encontrado en Moodle API")
            print(f"      - Username: {usuario_moodle.get('username')}")
            print(f"      - Fullname: {usuario_moodle.get('fullname')}")
            print(f"      - Email: {usuario_moodle.get('email')}")
            print(f"      - Last access (curso): {usuario_moodle.get('lastcourseaccess')} (Unix timestamp)")

            # Convertir timestamp
            last_access = usuario_moodle.get('lastcourseaccess', 0)
            if last_access and last_access > 0:
                from datetime import datetime
                fecha = datetime.fromtimestamp(last_access)
                print(f"      - Last access (fecha): {fecha.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"      - Last access (fecha): NUNCA (timestamp = {last_access})")

            # Grupos
            grupos = usuario_moodle.get('groups', [])
            print(f"      - Grupos: {len(grupos)}")
            if grupos:
                for g in grupos:
                    print(f"         - {g.get('name')}: {g.get('description', 'Sin descripción')}")
        else:
            print(f"   ❌ No encontrado en Moodle API")

    except Exception as e:
        print(f"   ⚠️  Error consultando Moodle API: {e}")

print("\n" + "=" * 80)
print("CONCLUSIONES")
print("=" * 80)
print("""
Si el usuario aparece en SENCE pero con lastcourseaccess = 0 en Moodle:
→ Esto significa que el usuario se inscribió pero NUNCA entró al curso en Moodle
→ Las conexiones SENCE podrían ser de otra plataforma o sistema
→ O podría ser un error en los datos de SENCE (conexiones de otro usuario)
""")
