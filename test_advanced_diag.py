"""Diagnóstico avanzado para identificar por qué Mail.Read no funciona después de 11 horas"""
import requests
import json
import base64
import os
import sys
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 70)
print("DIAGNÓSTICO AVANZADO - 11 horas después")
print("=" * 70)

# Test 1: Token normal
print("\n1. Token con scope .default")
r = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
)
if r.status_code == 200:
    token1 = r.json()["access_token"]
    payload = token1.split(".")[1] + "=" * (4 - len(token1.split(".")[1]) % 4)
    decoded1 = json.loads(base64.b64decode(payload))
    print(f"   Roles: {decoded1.get('roles', [])}")
    print(f"   iat: {decoded1.get('iat')}")
    print(f"   exp: {decoded1.get('exp')}")
else:
    print(f"   Error: {r.status_code}")

# Test 2: Token con scope específico Mail.Read
print("\n2. Token con scope específico https://graph.microsoft.com/Mail.Read")
r2 = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/Mail.Read",
        "grant_type": "client_credentials"
    }
)
print(f"   Status: {r2.status_code}")
if r2.status_code == 200:
    token2 = r2.json()["access_token"]
    payload2 = token2.split(".")[1] + "=" * (4 - len(token2.split(".")[1]) % 4)
    decoded2 = json.loads(base64.b64decode(payload2))
    print(f"   Roles: {decoded2.get('roles', [])}")
else:
    print(f"   Error: {r2.text[:300]}")

# Test 3: Verificar service principal
print("\n3. Verificar Service Principal de la app")
if r.status_code == 200:
    headers = {"Authorization": f"Bearer {token1}"}
    # Intentar obtener info del service principal
    sp_url = f"https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '{client_id}'"
    r3 = requests.get(sp_url, headers=headers)
    print(f"   Status: {r3.status_code}")
    if r3.status_code == 200:
        sp_data = r3.json().get("value", [])
        if sp_data:
            sp = sp_data[0]
            print(f"   Service Principal ID: {sp.get('id')}")
            print(f"   Display Name: {sp.get('displayName')}")
            # Ver los app roles asignados
            app_roles = sp.get('appRoles', [])
            print(f"   App Roles definidos: {len(app_roles)}")
        else:
            print("   ⚠️  Service Principal no encontrado")
    else:
        print(f"   Error obteniendo SP: {r3.text[:200]}")

# Test 4: Intentar acceso directo a diferentes endpoints
print("\n4. Test de acceso a diferentes endpoints")
if r.status_code == 200:
    headers = {"Authorization": f"Bearer {token1}"}

    tests = [
        ("Leer info@", "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=1"),
        ("Leer jortizleiva@", "https://graph.microsoft.com/v1.0/users/jortizleiva@duocapital.cl/messages?$top=1"),
        ("Listar usuarios", "https://graph.microsoft.com/v1.0/users?$top=1"),
        ("Me (user context)", "https://graph.microsoft.com/v1.0/me/messages?$top=1"),
    ]

    for name, url in tests:
        r4 = requests.get(url, headers=headers)
        print(f"   {name}: {r4.status_code}")
        if r4.status_code not in (200, 403, 404):
            print(f"      {r4.text[:150]}")

print("\n" + "=" * 70)
print("CONCLUSIONES:")
print("=" * 70)

if 'Mail.Read' in decoded1.get('roles', []):
    print("✅ Mail.Read SÍ está en el token con scope .default")
    print("   El problema NO es de permisos. Puede ser del buzón o usuario.")
else:
    print("❌ Mail.Read NO está en el token después de 11 horas")
    print("   Esto NO es normal. Posibles causas:")
    print("   1. El admin consent no se aplicó correctamente")
    print("   2. Hay un problema con el Service Principal de la app")
    print("   3. Azure AD tiene algún problema/bug con esta app")
    print()
    print("SOLUCIÓN RECOMENDADA:")
    print("   Opción A: Revocar y re-conceder TODOS los permisos")
    print("   Opción B: Crear una nueva App Registration desde cero")

print("=" * 70)
