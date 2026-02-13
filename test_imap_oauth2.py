"""Test IMAP OAuth2 con IMAP.AccessAsApp de Office 365 Exchange Online"""
import requests
import json
import base64
import os
import sys
import imaplib
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 70)
print("TEST: IMAP OAuth2 con IMAP.AccessAsApp")
print("=" * 70)

# 1. Obtener token con scope de Outlook (NO Graph)
print("\n1. Obteniendo token con scope Outlook...")
token_resp = requests.post(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://outlook.office365.com/.default",
        "grant_type": "client_credentials"
    }
)

if token_resp.status_code != 200:
    print(f"❌ Error obteniendo token: {token_resp.text}")
    sys.exit(1)

token = token_resp.json()["access_token"]
print("✅ Token obtenido")

# Decodificar y mostrar roles
payload = token.split(".")[1]
payload += "=" * (4 - len(payload) % 4)
decoded = json.loads(base64.b64decode(payload))
roles = decoded.get("roles", [])
print(f"   Roles en token: {roles}")

if "IMAP.AccessAsApp" not in roles:
    print("\n⏳ IMAP.AccessAsApp NO está en el token todavía")
    print("   Espera 10-15 minutos más para propagación")
    sys.exit(0)

print("\n✅ IMAP.AccessAsApp SÍ está en el token!")

# 2. Conectar a IMAP con OAuth2
print("\n2. Conectando a outlook.office365.com vía IMAP...")
try:
    mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    print("✅ Conexión IMAP establecida")

    # 3. Autenticar con XOAUTH2
    print("\n3. Autenticando con XOAUTH2...")
    user = "info@duocapital.cl"
    auth_string = f"user={user}\x01auth=Bearer {token}\x01\x01"

    mail.authenticate("XOAUTH2", lambda x: auth_string.encode())
    print("✅ Autenticación exitosa!")

    # 4. Listar carpetas
    print("\n4. Listando carpetas...")
    status, folders = mail.list()
    if status == "OK":
        print(f"✅ {len(folders)} carpetas encontradas")
        print("   Primeras 5 carpetas:")
        for folder in folders[:5]:
            print(f"      {folder.decode('utf-8')}")

    # 5. Seleccionar INBOX y contar correos
    print("\n5. Seleccionando INBOX...")
    status, messages = mail.select("INBOX")
    if status == "OK":
        num_msgs = int(messages[0])
        print(f"✅ INBOX seleccionado: {num_msgs} correos totales")

        # 6. Buscar últimos 3 correos
        print("\n6. Buscando últimos 3 correos...")
        status, msg_ids = mail.search(None, "ALL")
        if status == "OK":
            msg_list = msg_ids[0].split()
            last_3 = msg_list[-3:] if len(msg_list) >= 3 else msg_list

            print(f"✅ Obteniendo {len(last_3)} correos recientes...")
            for msg_id in last_3:
                status, data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (SUBJECT FROM DATE)])")
                if status == "OK":
                    headers = data[0][1].decode('utf-8', errors='ignore')
                    print(f"\n   Correo #{msg_id.decode()}:")
                    for line in headers.split('\r\n'):
                        if line.strip():
                            print(f"      {line}")

    # Cerrar conexión
    mail.logout()

    print("\n" + "=" * 70)
    print("✅✅✅ TODO FUNCIONA!")
    print("=" * 70)
    print("IMAP.AccessAsApp está funcionando correctamente.")
    print("\nPRÓXIMOS PASOS:")
    print("1. Modificar src/ingest/email_reader.py para usar OAuth2")
    print("2. Reemplazar autenticación por password con XOAUTH2")
    print("3. Probar en local y luego desplegar al servidor")

except imaplib.IMAP4.error as e:
    print(f"\n❌ Error de autenticación IMAP: {e}")
    print("\nPosibles causas:")
    print("1. IMAP.AccessAsApp aún no propagado (espera 10-15 min más)")
    print("2. El buzón info@duocapital.cl no tiene IMAP habilitado")
    print("3. Falta configurar 'impersonation' en Exchange Online")
except Exception as e:
    print(f"\n❌ Error inesperado: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
