"""Test rápido: verificar que Mail.Send funciona"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from src.reports.email_sender import enviar_correo

print("=" * 60)
print("TEST: Mail.Send (enviar correo)")
print("=" * 60)

resultado = enviar_correo(
    destinatario="jortizleiva@duocapital.cl",
    asunto="[TEST] Verificación Mail.Send",
    cuerpo_html="<p>Test de que Mail.Send funciona correctamente.</p>",
    dry_run=False
)

print(f"\nResultado: {resultado['status']}")
print(f"Detalle: {resultado['detalle']}")

if resultado['status'] == 'OK':
    print("\n✅ Mail.Send FUNCIONA")
    print("   Entonces Mail.Read también debería funcionar si está bien configurado")
else:
    print(f"\n❌ Mail.Send NO funciona: {resultado['detalle']}")
