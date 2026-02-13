"""Diagnóstico detallado de acceso a Graph API"""
import requests
import os
import sys
from dotenv import load_dotenv

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 70)
print("DIAGNÓSTICO DETALLADO: Graph API Mail.Read")
print("=" * 70)

# 1. Verificar credenciales
print("\n1. VERIFICACIÓN DE CREDENCIALES")
print("-" * 70)
print(f"TENANT_ID present: {bool(tenant_id)}, starts with: {tenant_id[:8] if tenant_id else 'EMPTY'}")
print(f"CLIENT_ID present: {bool(client_id)}, starts with: {client_id[:8] if client_id else 'EMPTY'}")
print(f"CLIENT_SECRET present: {bool(client_secret)}, starts with: {client_secret[:4] if client_secret else 'EMPTY'}")

if not all([tenant_id, client_id, client_secret]):
    print("\n❌ FALTA ALGUNA CREDENCIAL EN .env")
    sys.exit(1)

# 2. Obtener token
print("\n2. OBTENIENDO TOKEN")
print("-" * 70)
token_resp = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
)

print(f"Token status: {token_resp.status_code}")

if token_resp.status_code != 200:
    print(f"❌ ERROR OBTENIENDO TOKEN")
    print(f"Response completo:\n{token_resp.text}")
    sys.exit(1)

token = token_resp.json()["access_token"]
print(f"✅ Token obtenido")
print(f"Token (primeros 20 chars): {token[:20]}...")

# 3. Test 1: Leer correos de info@duocapital.cl
print("\n3. TEST 1: info@duocapital.cl")
print("-" * 70)
r1 = requests.get(
    "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=1",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"Status: {r1.status_code}")
print(f"Response completo:\n{r1.text}")

# 4. Test 2: Leer correos de jortizleiva@duocapital.cl
print("\n4. TEST 2: jortizleiva@duocapital.cl (para comparar)")
print("-" * 70)
r2 = requests.get(
    "https://graph.microsoft.com/v1.0/users/jortizleiva@duocapital.cl/messages?$top=1",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"Status: {r2.status_code}")
print(f"Response completo:\n{r2.text}")

# 5. Test 3: Ver permisos del token
print("\n5. TEST 3: Información del tenant")
print("-" * 70)
r3 = requests.get(
    "https://graph.microsoft.com/v1.0/organization",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"Status: {r3.status_code}")
if r3.status_code == 200:
    org_data = r3.json()
    if org_data.get("value"):
        org = org_data["value"][0]
        print(f"Organización: {org.get('displayName', 'N/A')}")
        print(f"Tenant ID verificado: {org.get('id', 'N/A')}")

# 6. Test 4: Listar usuarios (para verificar que info@ existe)
print("\n6. TEST 4: Verificar que info@duocapital.cl existe")
print("-" * 70)
r4 = requests.get(
    "https://graph.microsoft.com/v1.0/users/info@duocapital.cl",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"Status: {r4.status_code}")
if r4.status_code == 200:
    user = r4.json()
    print(f"✅ Usuario existe: {user.get('userPrincipalName', 'N/A')}")
    print(f"   Display Name: {user.get('displayName', 'N/A')}")
    print(f"   Mail: {user.get('mail', 'N/A')}")
else:
    print(f"Response: {r4.text}")

print("\n" + "=" * 70)
print("FIN DEL DIAGNÓSTICO")
print("=" * 70)
