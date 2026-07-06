#!/usr/bin/env python3
"""Procesa un lote de certificados de participación en segundo plano.

Se lanza desde la web (subprocess desacoplado) o manualmente. Es seguro
relanzarlo: los certificados ya enviados se saltan (reanudación tras caída).

Uso:
    venv/bin/python scripts/emitir_certificados.py <lote_id> [--dry-run]
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("emitir_certificados")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    lote_id = sys.argv[1]
    dry_run = "--dry-run" in sys.argv[2:]

    from src.certificados.emitter import procesar_lote

    try:
        resumen = procesar_lote(lote_id, dry_run=dry_run)
    except Exception as e:
        logger.error("Fallo procesando lote %s: %s", lote_id, e, exc_info=True)
        try:
            from src.certificados import registry
            registry.actualizar_lote(lote_id, estado="error", detalle=str(e))
        except Exception:
            pass
        sys.exit(2)

    sys.exit(0 if resumen["errores"] == 0 else 3)


if __name__ == "__main__":
    main()
