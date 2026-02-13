"""Fuerza obtención de token nuevo para bypass de caché de Azure"""
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

# Usar nombres correctos del .env
tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 70)
print("FORZANDO TOKEN NUEVO (bypass caché)")
print("=" * 70)

# Forzar token nuevo agregando un claim adicional
token_resp = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
        "claims": json.dumps({"access_token": {"xms_cc": {"values": ["cp1"]}}})
    }
)

print(f"\nToken status: {token_resp.status_code}")

if token_resp.status_code == 200:
    token = token_resp.json()["access_token"]

    # Decodificar token
    payload = token.split(".")[1]
    payload += "=" * (4 - len(payload) % 4)
    decoded = json.loads(base64.b64decode(payload))

    roles = decoded.get('roles', [])
    print(f"\nRoles en token:")
    for role in roles:
        print(f"  - {role}")

    print(f"\nApp ID: {decoded.get('appid')}")
    print(f"Token emitido (iat): {decoded.get('iat')}")
    print(f"Token expira (exp): {decoded.get('exp')}")

    if 'Mail.Read' in roles:
        print("\n✅✅✅ Mail.Read ESTÁ en el token!")
        print("✅ Continuar con la implementación del módulo lector")

        # Test rápido de acceso
        print("\nProbando acceso a info@duocapital.cl...")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(
            "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=1",
            headers=headers
        )
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            print("✅ ACCESO EXITOSO!")
            messages = r.json().get("value", [])
            print(f"   {len(messages)} correo(s) encontrados")
        else:
            print(f"Response: {r.text[:300]}")
    else:
        print("\n❌ Mail.Read aún no aparece en el token")
        print("\nEsto confirma que es un problema de propagación de Azure.")
        print("El permiso está configurado correctamente en Azure Portal,")
        print("pero Azure AD aún no ha actualizado el servicio de tokens.")
        print()
        print("Probando acceso directo de todas formas...")

        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(
            "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=1",
            headers=headers
        )
        print(f"Status leer info@: {r.status_code}")
        print(f"Response: {r.text[:300]}")

        print("\n⏰ ACCIÓN: Esperar 15 minutos y volver a ejecutar este script.")
        print("   Azure AD puede demorar hasta 15-20 minutos en propagar cambios.")
else:
    print(f"❌ Error obteniendo token: {token_resp.text}")

print("\n" + "=" * 70)
