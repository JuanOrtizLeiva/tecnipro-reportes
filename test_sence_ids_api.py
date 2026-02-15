"""Test: Obtener IDs SENCE desde Moodle API."""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

from src.ingest import moodle_api_client as api
from config import settings

print("=" * 60)
print("TEST: Obtener IDs SENCE desde Moodle API")
print("=" * 60)
print(f"\nModo actual: DATA_SOURCE={settings.DATA_SOURCE}")
print(f"Categorías: {settings.MOODLE_CATEGORY_IDS}")

print("\n🔍 Obteniendo IDs SENCE...")
try:
    sence_ids = api.get_all_sence_ids()

    print(f"\n✅ IDs SENCE encontrados: {len(sence_ids)}")
    print(f"\nLista de IDs:")
    for idx, id_sence in enumerate(sence_ids, 1):
        print(f"  [{idx:2d}] {id_sence}")

    if sence_ids:
        print(f"\n📊 Primer ID: {sence_ids[0]}")
        print(f"📊 Último ID: {sence_ids[-1]}")

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
