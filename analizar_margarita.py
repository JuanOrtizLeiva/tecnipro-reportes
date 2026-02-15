"""Analizar filas de Margarita en archivo SENCE."""

import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

df = pd.read_excel('data/sence/6763149.csv')

print("=" * 80)
print("ANÁLISIS: Margarita Victoria en archivo SENCE 6763149")
print("=" * 80)

margarita = df[df['Rut Participante'].astype(str).str.contains('11.912.163', na=False)]

print(f"\nTotal de filas para Margarita: {len(margarita)}")

if len(margarita) > 0:
    print("\nDatos de cada fila:")
    for i, (idx, fila) in enumerate(margarita.iterrows(), 1):
        print(f"\n--- Fila {i} ---")
        print(f"RUT: {fila['Rut Participante']}")
        print(f"Nombre: {fila['Nombre Participante']}")
        print(f"Fecha Inicio: {fila['Fecha Inicio Conectividad']}")
        print(f"Fecha Fin: {fila['Fecha Término Conectividad']}")
        print(f"Tiempo: {fila['Tiempo Conectividad']}")

        # Verificar si las fechas son válidas
        fecha_inicio_valida = pd.notna(fila['Fecha Inicio Conectividad'])
        print(f"¿Fecha válida?: {fecha_inicio_valida}")
else:
    print("\n❌ Margarita NO está en el archivo")

# Ver todas las filas del archivo
print("\n" + "=" * 80)
print("TODOS LOS PARTICIPANTES en archivo 6763149")
print("=" * 80)
print(f"\nTotal filas: {len(df)}")

participantes_unicos = df['Rut Participante'].unique()
print(f"Participantes únicos: {len(participantes_unicos)}")

for rut in participantes_unicos:
    filas_part = df[df['Rut Participante'] == rut]
    nombre = filas_part.iloc[0]['Nombre Participante']
    con_fecha = filas_part['Fecha Inicio Conectividad'].notna().sum()
    print(f"\n- {rut} ({nombre}): {len(filas_part)} fila(s), {con_fecha} con fecha válida")
