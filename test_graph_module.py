"""Test del módulo Graph Mail Reader.

Ejecutar este script para probar la descarga de correos via Graph API
cuando los permisos de Mail.Read estén propagados.
"""
import sys
import logging

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

print("=" * 70)
print("TEST: Módulo Graph Mail Reader")
print("=" * 70)

try:
    from src.ingest.graph_mail_reader import descargar_adjuntos_moodle_graph

    print("\n✅ Módulo importado correctamente")
    print("\nEjecutando descarga de correos via Graph API...")
    print("-" * 70)

    resultado = descargar_adjuntos_moodle_graph()

    print("\n" + "=" * 70)
    print("RESULTADO DEL TEST")
    print("=" * 70)
    print(f"Status: {resultado['status']}")
    print(f"Archivos descargados: {len(resultado['archivos_descargados'])}")
    if resultado['archivos_descargados']:
        for archivo in resultado['archivos_descargados']:
            print(f"  - {archivo}")
    print(f"Detalle: {resultado['detalle']}")
    print("=" * 70)

    if resultado['status'] == 'OK':
        print("\n✅✅✅ TEST EXITOSO!")
        print("El módulo Graph API está funcionando correctamente.")
        print("\nPróximos pasos:")
        print("1. Verificar que los archivos se descargaron en data/")
        print("2. Cuando estés listo para migrar, modificar run_daily_production.sh")
        print("   para usar descargar_adjuntos_moodle_graph() en vez de email IMAP")
    elif resultado['status'] == 'PARCIAL':
        print("\n⚠️  TEST PARCIAL")
        print("Algunos archivos se descargaron pero no todos.")
        print("Verifica que Moodle haya enviado ambos reportes.")
    else:
        print("\n❌ TEST FALLÓ")
        print("Revisa el detalle del error arriba.")
        print("\nSi el error es 403, los permisos aún no se han propagado.")
        print("Espera 10 minutos más y vuelve a ejecutar este test.")

except ImportError as e:
    print(f"\n❌ Error importando módulo: {e}")
    print("Verifica que graph_mail_reader.py existe en src/ingest/")
except Exception as e:
    print(f"\n❌ Error ejecutando test: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
