"""
Script de verificación - Tecnipro Reportes
==========================================
Ejecutar con: python test_setup.py

Verifica que:
1. El archivo .env existe y tiene las credenciales
2. Los CSV de Moodle se pueden leer
3. Los CSV de SENCE se pueden leer
4. El Excel de compradores se puede leer
5. La conexión a Azure/OneDrive funciona
"""

import os
import sys

def print_ok(msg):
    print(f"  ✅ {msg}")

def print_fail(msg):
    print(f"  ❌ {msg}")

def print_warn(msg):
    print(f"  ⚠️  {msg}")

def print_header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

errors = []

# ============================================================
# TEST 1: Verificar que .env existe y tiene contenido
# ============================================================
print_header("TEST 1: Archivo .env")

env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    print_ok(f"Archivo .env encontrado en: {env_path}")
    
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_vars = {
        'AZURE_CLIENT_ID': 'Azure Client ID',
        'AZURE_TENANT_ID': 'Azure Tenant ID', 
        'AZURE_CLIENT_SECRET': 'Azure Client Secret',
        'CLAVE_UNICA_RUT': 'RUT Clave Única',
        'DATA_INPUT_PATH': 'Ruta datos de entrada',
        'SENCE_CSV_PATH': 'Ruta CSVs SENCE',
        'COMPRADORES_PATH': 'Ruta Excel compradores',
    }
    
    for var, desc in required_vars.items():
        if var in content:
            # Verificar que no tenga el valor placeholder
            line = [l for l in content.split('\n') if l.startswith(var + '=')]
            if line:
                value = line[0].split('=', 1)[1].strip()
                if 'PEGAR' in value or value == '':
                    print_fail(f"{desc} ({var}): FALTA COMPLETAR - aún tiene el valor de ejemplo")
                    errors.append(f"{var} no completado")
                else:
                    # Mostrar solo primeros 8 caracteres por seguridad
                    masked = value[:8] + "..." if len(value) > 8 else value
                    print_ok(f"{desc} ({var}): {masked}")
        else:
            print_fail(f"{desc} ({var}): NO ENCONTRADA en .env")
            errors.append(f"{var} no encontrada")
else:
    print_fail(f"Archivo .env NO encontrado en: {env_path}")
    print_warn("¿Guardaste el archivo como .env.txt en vez de .env?")
    
    # Verificar si existe como .env.txt
    env_txt_path = os.path.join(os.path.dirname(__file__), '.env.txt')
    if os.path.exists(env_txt_path):
        print_warn("ENCONTRADO como .env.txt — Renómbralo a .env (quita el .txt)")
    errors.append(".env no existe")

# ============================================================
# TEST 2: Verificar archivos CSV de Moodle
# ============================================================
print_header("TEST 2: Archivos CSV de Moodle")

data_path = os.path.join(os.path.dirname(__file__), 'data')

if os.path.exists(data_path):
    print_ok(f"Carpeta data/ encontrada")
    
    # Greporte
    greporte_path = None
    for f in os.listdir(data_path):
        if f.lower().startswith('g') and f.lower().endswith('.csv'):
            greporte_path = os.path.join(data_path, f)
            break
    
    if greporte_path:
        try:
            with open(greporte_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            print_ok(f"Greporte encontrado: {os.path.basename(greporte_path)} ({len(lines)-1} filas de datos)")
        except Exception as e:
            print_fail(f"Error leyendo Greporte: {e}")
            errors.append("Greporte no se puede leer")
    else:
        print_fail("Greporte.csv NO encontrado en data/")
        errors.append("Greporte.csv falta")
    
    # Dreporte
    dreporte_path = None
    for f in os.listdir(data_path):
        if f.lower().startswith('d') and f.lower().endswith('.csv'):
            dreporte_path = os.path.join(data_path, f)
            break
    
    if dreporte_path:
        try:
            with open(dreporte_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            print_ok(f"Dreporte encontrado: {os.path.basename(dreporte_path)} ({len(lines)-1} filas de datos)")
        except Exception as e:
            print_fail(f"Error leyendo Dreporte: {e}")
            errors.append("Dreporte no se puede leer")
    else:
        print_fail("Dreporte.csv NO encontrado en data/")
        errors.append("Dreporte.csv falta")
else:
    print_fail("Carpeta data/ NO encontrada")
    errors.append("Carpeta data/ falta")

# ============================================================
# TEST 3: Verificar archivos SENCE
# ============================================================
print_header("TEST 3: Archivos CSV de SENCE")

sence_path = os.path.join(os.path.dirname(__file__), 'data', 'sence')

if os.path.exists(sence_path):
    csv_files = [f for f in os.listdir(sence_path) if f.endswith('.csv')]
    if csv_files:
        print_ok(f"Carpeta data/sence/ encontrada con {len(csv_files)} archivos CSV")
        
        vacios = 0
        con_datos = 0
        for csv_file in sorted(csv_files):
            filepath = os.path.join(sence_path, csv_file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                # Filtrar líneas vacías
                data_lines = [l for l in lines if l.strip()]
                if len(data_lines) == 0:
                    vacios += 1
                else:
                    con_datos += 1
                    print_ok(f"  {csv_file}: {len(data_lines)} registros")
            except Exception as e:
                print_fail(f"  Error leyendo {csv_file}: {e}")
        
        if vacios > 0:
            print_warn(f"  {vacios} archivos SENCE están vacíos (es normal para algunos cursos)")
        print_ok(f"  Resumen: {con_datos} con datos, {vacios} vacíos")
    else:
        print_fail("Carpeta data/sence/ existe pero no tiene archivos CSV")
        errors.append("Sin CSVs SENCE")
else:
    print_fail("Carpeta data/sence/ NO encontrada")
    errors.append("Carpeta sence/ falta")

# ============================================================
# TEST 4: Verificar Excel de compradores
# ============================================================
print_header("TEST 4: Excel de compradores")

compradores_path = os.path.join(os.path.dirname(__file__), 'data', 'config', 'compradores_tecnipro.xlsx')

if os.path.exists(compradores_path):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(compradores_path, read_only=True)
        ws = wb['Compradores']
        
        # Contar filas con datos
        total_rows = 0
        rows_with_buyer = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is not None:  # ID Curso Moodle
                total_rows += 1
                if row[4] is not None and str(row[4]).strip():  # Comprador nombre
                    rows_with_buyer += 1
        
        wb.close()
        print_ok(f"Excel encontrado: {total_rows} cursos registrados")
        
        if rows_with_buyer == 0:
            print_warn(f"NINGÚN curso tiene comprador asignado — recuerda llenar las columnas amarillas")
        elif rows_with_buyer < total_rows:
            print_warn(f"{rows_with_buyer} de {total_rows} cursos tienen comprador asignado (faltan {total_rows - rows_with_buyer})")
        else:
            print_ok(f"Todos los cursos tienen comprador asignado")
            
    except ImportError:
        print_warn("openpyxl no instalado — instalar con: pip install openpyxl")
        print_warn("No se pudo verificar el Excel, pero el archivo existe")
    except Exception as e:
        print_fail(f"Error leyendo Excel: {e}")
        errors.append("Excel de compradores no se puede leer")
else:
    print_fail(f"Excel NO encontrado en: {compradores_path}")
    errors.append("Excel compradores falta")

# ============================================================
# TEST 5: Verificar conexión Azure (OneDrive)
# ============================================================
print_header("TEST 5: Conexión Azure / OneDrive")

try:
    # Leer variables del .env manualmente (sin python-dotenv)
    azure_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    azure_vars[key.strip()] = value.strip()
    
    client_id = azure_vars.get('AZURE_CLIENT_ID', '')
    tenant_id = azure_vars.get('AZURE_TENANT_ID', '')
    client_secret = azure_vars.get('AZURE_CLIENT_SECRET', '')
    
    if not client_id or not tenant_id or not client_secret or 'PEGAR' in client_secret:
        print_warn("Credenciales Azure incompletas — no se puede probar conexión")
        print_warn("Completa AZURE_CLIENT_SECRET en el archivo .env")
    else:
        try:
            import urllib.request
            import urllib.parse
            import json
            
            # Intentar obtener token de Azure
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            
            data = urllib.parse.urlencode({
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': 'https://graph.microsoft.com/.default',
                'grant_type': 'client_credentials'
            }).encode()
            
            req = urllib.request.Request(token_url, data=data, method='POST')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode())
                
            if 'access_token' in result:
                print_ok("Conexión a Azure exitosa — token obtenido")
                
                # Intentar listar sites de SharePoint
                token = result['access_token']
                graph_url = "https://graph.microsoft.com/v1.0/sites?search=duocapital"
                req2 = urllib.request.Request(graph_url)
                req2.add_header('Authorization', f'Bearer {token}')
                
                with urllib.request.urlopen(req2, timeout=10) as response2:
                    sites = json.loads(response2.read().decode())
                
                if sites.get('value'):
                    for site in sites['value']:
                        print_ok(f"SharePoint site encontrado: {site.get('displayName', 'sin nombre')}")
                else:
                    print_warn("No se encontraron sites de SharePoint — puede que necesites ajustar permisos")
            else:
                print_fail(f"Azure respondió pero sin token: {result}")
                errors.append("Azure sin token")
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            print_fail(f"Error de Azure (HTTP {e.code})")
            if 'invalid_client' in error_body:
                print_fail("El Client Secret es incorrecto — verifica en Azure Portal")
                errors.append("Azure Client Secret incorrecto")
            elif 'unauthorized_client' in error_body:
                print_fail("La app no tiene los permisos correctos — revisa API permissions en Azure")
                errors.append("Azure permisos incorrectos")
            else:
                print_fail(f"Detalle: {error_body[:200]}")
                errors.append("Azure error de conexión")
        except Exception as e:
            print_fail(f"Error conectando a Azure: {e}")
            errors.append("Azure error de conexión")
            
except Exception as e:
    print_fail(f"Error general en test Azure: {e}")
    errors.append("Test Azure falló")

# ============================================================
# RESUMEN FINAL
# ============================================================
print_header("RESUMEN")

if not errors:
    print_ok("¡TODO CORRECTO! Estás listo para ejecutar las instrucciones de Codex.")
    print()
    print("  Siguiente paso: abre Claude Code y pega las instrucciones de Fase 1.")
else:
    print_fail(f"Se encontraron {len(errors)} problema(s):")
    for err in errors:
        print(f"     • {err}")
    print()
    print("  Corrige estos problemas antes de continuar con Codex.")

print()
