"""Decodifica JWT token para ver permisos reales y detectar mismatch de apps"""
import requests
import base64
import json
import os
import sys
from dotenv import load_dotenv

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# Leer credenciales del .env (usar nombres EXACTOS del proyecto)
tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 70)
print("DIAGNÓSTICO: Verificar permisos reales del token")
print("=" * 70)

print("\n=== CREDENCIALES DEL .ENV ===")
if tenant_id:
    print(f"AZURE_TENANT_ID: {tenant_id[:8]}...{tenant_id[-4:]}")
else:
    print("AZURE_TENANT_ID: ❌ VACÍO")

if client_id:
    print(f"AZURE_CLIENT_ID: {client_id}")
    print(f"                 (primeros 8): {client_id[:8]}...")
else:
    print("AZURE_CLIENT_ID: ❌ VACÍO")

if client_secret:
    print(f"AZURE_CLIENT_SECRET: {client_secret[:4]}...{client_secret[-4:]}")
else:
    print("AZURE_CLIENT_SECRET: ❌ VACÍO")

if not all([tenant_id, client_id, client_secret]):
    print("\n❌ Faltan credenciales en .env")
    sys.exit(1)

# Obtener token
print("\n=== OBTENIENDO TOKEN ===")
token_resp = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
)

print(f"Status: {token_resp.status_code}")

if token_resp.status_code != 200:
    print(f"❌ Error obteniendo token: {token_resp.text}")
    sys.exit(1)

token = token_resp.json()["access_token"]
print("✅ Token obtenido correctamente")

# Decodificar JWT para ver los permisos reales
print("\n=== DECODIFICANDO TOKEN JWT ===")
try:
    # El JWT tiene 3 partes separadas por puntos: header.payload.signature
    # Necesitamos el payload (segunda parte)
    payload_encoded = token.split(".")[1]

    # Agregar padding si es necesario (base64 requiere múltiplo de 4)
    payload_encoded += "=" * (4 - len(payload_encoded) % 4)

    # Decodificar de base64
    decoded = json.loads(base64.b64decode(payload_encoded))

    print(f"App ID en el token: {decoded.get('appid', 'NO ENCONTRADO')}")
    print(f"Tenant ID en el token: {decoded.get('tid', 'NO ENCONTRADO')}")
    print(f"Audience: {decoded.get('aud', 'NO ENCONTRADO')}")

    # CRÍTICO: Los permisos están en 'roles'
    roles = decoded.get('roles', [])
    print(f"\nROLES/PERMISOS en el token:")
    if roles:
        for role in roles:
            print(f"  ✅ {role}")
    else:
        print("  ❌ NINGUNO - El token NO tiene permisos")

    # Verificar si hay mismatch
    print("\n=== VERIFICACIÓN DE COINCIDENCIA ===")
    token_app_id = decoded.get('appid', '')

    if token_app_id != client_id:
        print(f"❌ MISMATCH DETECTADO!")
        print(f"   CLIENT_ID del .env:  {client_id}")
        print(f"   App ID en el token:  {token_app_id}")
        print("\n   PROBLEMA: Las credenciales del .env NO corresponden")
        print("   a la misma app del token. Esto es muy raro.")
    else:
        print(f"✅ App ID coincide: {client_id}")

    # Diagnóstico final
    print("\n=== DIAGNÓSTICO FINAL ===")
    if not roles:
        print("❌ EL TOKEN NO TIENE PERMISOS (roles vacío)")
        print("\nEsto significa que la app con CLIENT_ID:")
        print(f"   {client_id}")
        print("\nNO tiene permisos configurados en Azure Portal.")
        print("\n📋 ACCIÓN REQUERIDA:")
        print("1. Ve a Azure Portal → Azure Active Directory → App registrations")
        print(f"2. Busca la app con Client ID: {client_id}")
        print("3. Verifica que ESA app tenga los permisos:")
        print("   - Mail.Read (Application)")
        print("   - User.Read.All (Application)")
        print("4. Verifica que ambos tengan 'Grant admin consent'")
        print("\nSi esa app NO existe o NO es la que revisaste,")
        print("significa que estás configurando permisos en una app DIFERENTE.")
    elif 'Mail.Read' not in roles:
        print(f"⚠️  El token tiene permisos pero NO incluye Mail.Read")
        print(f"   Permisos actuales: {roles}")
        print(f"\n   Falta agregar Mail.Read a la app: {client_id}")
    else:
        print(f"✅ El token tiene Mail.Read")
        print(f"   Permisos completos: {roles}")

except Exception as e:
    print(f"❌ Error decodificando token: {e}")

print("\n" + "=" * 70)
