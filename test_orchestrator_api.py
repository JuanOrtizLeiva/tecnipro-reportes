"""Test: Orchestrator con modo API."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.scraper.orchestrator import ScraperOrchestrator
from config import settings

print("=" * 60)
print("TEST: Orchestrator - get_sence_ids() en modo API")
print("=" * 60)
print(f"\nModo actual: DATA_SOURCE={settings.DATA_SOURCE}")

orchestrator = ScraperOrchestrator(headless=True)

print("\n🔍 Obteniendo IDs SENCE desde orchestrator...")
try:
    sence_ids = orchestrator.get_sence_ids()

    print(f"\n✅ IDs SENCE obtenidos por orchestrator: {len(sence_ids)}")
    print(f"\nLista de IDs:")
    for idx, id_sence in enumerate(sence_ids, 1):
        print(f"  [{idx:2d}] {id_sence}")

    if sence_ids:
        print(f"\n📊 Resumen:")
        print(f"   - Total IDs: {len(sence_ids)}")
        print(f"   - Rango: {sence_ids[0]} → {sence_ids[-1]}")
        print(f"\n✅ El orchestrator está listo para ejecutar el scraper con estos IDs")

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
