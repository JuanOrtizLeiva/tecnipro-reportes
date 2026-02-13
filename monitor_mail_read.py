"""Monitor automático que verifica cada 2 minutos si Mail.Read funciona"""
import requests
import json
import base64
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")

print("=" * 70)
print("MONITOR AUTOMÁTICO - Mail.Read")
print("Verificando cada 2 minutos hasta que funcione...")
print("Presiona Ctrl+C para detener")
print("=" * 70)

intento = 0
while True:
    intento += 1
    hora = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{hora}] Intento #{intento}...")

    try:
        # Obtener token
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
            token = r.json()["access_token"]

            # Decodificar token
            payload = token.split(".")[1] + "=" * (4 - len(token.split(".")[1]) % 4)
            decoded = json.loads(base64.b64decode(payload))
            roles = decoded.get("roles", [])

            if "Mail.Read" in roles:
                print("\n" + "=" * 70)
                print("🎉🎉🎉 ¡FUNCIONA! Mail.Read está en el token")
                print("=" * 70)
                print(f"Roles completos: {roles}")

                # Test de acceso real
                headers = {"Authorization": f"Bearer {token}"}
                r2 = requests.get(
                    "https://graph.microsoft.com/v1.0/users/info@duocapital.cl/messages?$top=1",
                    headers=headers
                )
                print(f"\nTest de acceso a info@: {r2.status_code}")

                if r2.status_code == 200:
                    print("✅ Acceso exitoso!")
                    print("\nAhora puedes ejecutar:")
                    print("  python test_graph_module.py")
                else:
                    print(f"⚠️  Status inesperado: {r2.text[:200]}")

                break
            else:
                print(f"   ⏳ Mail.Read aún no está. Roles: {roles}")
        else:
            print(f"   ❌ Error obteniendo token: {r.status_code}")

    except KeyboardInterrupt:
        print("\n\n⚠️  Monitoreo detenido por el usuario")
        break
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Esperar 2 minutos antes del siguiente intento
    print(f"   Esperando 2 minutos... (próximo intento a las {datetime.now().strftime('%H:%M')})")
    try:
        time.sleep(120)  # 2 minutos
    except KeyboardInterrupt:
        print("\n\n⚠️  Monitoreo detenido por el usuario")
        break

print("\n" + "=" * 70)
