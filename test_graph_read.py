"""Test: verificar si Graph API puede leer correos de info@duocapital.cl"""
import requests
import os
import sys
from dotenv import load_dotenv

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 60)
print("TEST: Acceso a correos de info@duocapital.cl via Graph API")
print("=" * 60)

# Obtener token
token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
token_data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope": "https://graph.microsoft.com/.default",
    "grant_type": "client_credentials"
}

print("\n1. Obteniendo token...")
response = requests.post(token_url, data=token_data)
if response.status_code != 200:
    print(f"❌ ERROR obteniendo token: {response.status_code}")
    print(response.text)
    exit(1)

token = response.json()["access_token"]
print("✅ Token obtenido exitosamente")

# Intentar leer correos de info@duocapital.cl
print("\n2. Intentando leer correos de info@duocapital.cl...")
headers = {"Authorization": f"Bearer {token}"}
mail_url = "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=5&$select=subject,from,receivedDateTime,hasAttachments"

response = requests.get(mail_url, headers=headers)
print(f"\nStatus: {response.status_code}")

if response.status_code == 200:
    messages = response.json().get("value", [])
    print(f"✅ ACCESO EXITOSO! {len(messages)} correos encontrados:")
    for msg in messages:
        sender = msg.get('from', {}).get('emailAddress', {}).get('address', 'desconocido')
        print(f"  - [{msg['receivedDateTime'][:10]}] {msg['subject']}")
        print(f"    De: {sender}, Adjuntos: {msg['hasAttachments']}")
    print("\n✅ El sistema puede leer correos de info@duocapital.cl")
    print("✅ Continuar con la implementación del módulo lector")
elif response.status_code == 403:
    print("❌ PERMISO DENEGADO")
    print("\nLa aplicación de Azure NO tiene permiso Mail.Read.")
    print("\n📋 INSTRUCCIONES PARA EL USUARIO:")
    print("1. Ir a https://portal.azure.com")
    print("2. Azure Active Directory → App registrations")
    print(f"3. Buscar app con Client ID: {CLIENT_ID}")
    print("4. Click en 'API permissions'")
    print("5. Click en 'Add a permission' → Microsoft Graph → Application permissions")
    print("6. Buscar 'Mail.Read' → Seleccionar → Add permissions")
    print("7. Click en 'Grant admin consent for [tu organización]'")
    print("8. Esperar 1-2 minutos y volver a ejecutar este test")
    print(f"\nDetalle del error:\n{response.text}")
elif response.status_code == 404:
    print("❌ BUZÓN NO ENCONTRADO")
    print("\nVerificar que info@duocapital.cl existe en Microsoft 365")
    print(f"Detalle:\n{response.text}")
else:
    print(f"❌ Error inesperado: {response.text}")

print("\n" + "=" * 60)
