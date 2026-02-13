"""Test simple para verificar si Mail.Read ya funciona"""
import requests
import json
import os
import sys
import base64
from dotenv import load_dotenv

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# Usar nombres correctos del .env
tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 60)
print("TEST SIMPLE: Verificar Mail.Read")
print("=" * 60)

# Obtener token nuevo
print("\n1. Obteniendo token...")
token_resp = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }
)

if token_resp.status_code != 200:
    print(f"❌ Error obteniendo token: {token_resp.text}")
    sys.exit(1)

token = token_resp.json()["access_token"]
print("✅ Token obtenido")

headers = {"Authorization": f"Bearer {token}"}

# Test directo: leer correos de info@duocapital.cl
print("\n2. Intentando leer correos de info@duocapital.cl...")
r = requests.get(
    "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=3&$select=subject,receivedDateTime,from",
    headers=headers
)

print(f"\nStatus: {r.status_code}")

if r.status_code == 200:
    msgs = r.json().get("value", [])
    print(f"\n✅✅✅ FUNCIONA! {len(msgs)} correos encontrados:")
    for m in msgs:
        sender = m.get('from', {}).get('emailAddress', {}).get('address', 'desconocido')
        print(f"  {m['receivedDateTime'][:16]} - {m['subject']}")
        print(f"    De: {sender}")
    print("\n🎉 Mail.Read está funcionando!")
    print("✅ Puedes ejecutar: python test_graph_module.py")

elif r.status_code == 403:
    print("\n❌ AÚN 403 - Revisando token...")
    payload = token.split(".")[1]
    payload += "=" * (4 - len(payload) % 4)
    decoded = json.loads(base64.b64decode(payload))
    roles = decoded.get("roles", [])
    print(f"\nRoles en token: {roles}")

    if "Mail.Read" not in roles:
        print("\n⏳ Mail.Read NO está en el token todavía.")
        print("   Propagación pendiente. Espera 10-15 minutos más.")
    else:
        print("\n⚠️  Mail.Read SÍ está en el token pero da 403.")
        print("   Error completo:")
        print(f"   {r.text[:500]}")
else:
    print(f"\n❌ Error inesperado: {r.text[:500]}")

print("\n" + "=" * 60)
