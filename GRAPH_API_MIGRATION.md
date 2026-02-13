# Migración a Graph API para lectura de correos

## Estado actual

- ✅ **Módulo Graph API implementado**: `src/ingest/graph_mail_reader.py`
- ⏳ **Esperando propagación de permisos**: Mail.Read en Azure AD
- ✅ **Sistema actual funcionando**: Gmail IMAP (`email_reader.py`)

## Cuando los permisos estén listos

### Paso 1: Verificar que los permisos se propagaron

```bash
python test_force_new_token.py
```

**Resultado esperado:**
```
✅ Mail.Read ESTÁ en el token
```

### Paso 2: Probar el módulo Graph API

```bash
python test_graph_module.py
```

**Resultado esperado:**
```
✅✅✅ TEST EXITOSO!
El módulo Graph API está funcionando correctamente.
```

**Qué hace este test:**
- Se conecta a `info@duocapital.cl` via Graph API
- Busca correos de Moodle (últimas 48 horas)
- Descarga `Greporte.csv` y `Dreporte.csv`
- Los guarda en `data/`

### Paso 3: Actualizar Moodle

**IMPORTANTE:** Antes de migrar, actualiza Moodle para que envíe los reportes a:
- **Nueva dirección**: `info@duocapital.cl`
- **Dirección antigua**: `reportetecnipro@gmail.com` (dejar de usar)

### Paso 4: Modificar el script de producción

Editar `scripts/run_daily_production.sh`:

**Reemplazar esta sección** (líneas ~50-72):
```bash
# Paso 1: Descargar archivos Moodle — Email primero, OneDrive como backup
echo "[$(date)] Descargando archivos Moodle desde email..."
python3 -c "
from src.ingest.email_reader import descargar_adjuntos_moodle
try:
    resultado = descargar_adjuntos_moodle()
    if resultado['status'] == 'OK':
        print(f'Email OK: {len(resultado[\"archivos_descargados\"])} archivos descargados')
    else:
        print(f'Email PARCIAL: {resultado.get(\"archivos_faltantes\", [])}')
        exit(1)
except Exception as e:
    print(f'Email FALLÓ: {e}')
    exit(1)
" 2>&1 || {
    echo "[$(date)] WARN: Email falló, intentando OneDrive como backup..."
    python3 -c "
from src.ingest.onedrive_client import download_moodle_csvs
download_moodle_csvs()
" 2>&1 || {
        echo "[$(date)] ERROR: OneDrive también falló, usando archivos locales"
    }
}
```

**Por esta nueva sección:**
```bash
# Paso 1: Descargar archivos Moodle — Graph API primero, OneDrive como backup
echo "[$(date)] Descargando archivos Moodle desde Graph API (info@duocapital.cl)..."
python3 -c "
from src.ingest.graph_mail_reader import descargar_adjuntos_moodle_graph
try:
    resultado = descargar_adjuntos_moodle_graph()
    if resultado['status'] == 'OK':
        print(f'Graph API OK: {len(resultado[\"archivos_descargados\"])} archivos descargados')
    else:
        print(f'Graph API PARCIAL: {resultado.get(\"detalle\", \"\")}')
        exit(1)
except Exception as e:
    print(f'Graph API FALLÓ: {e}')
    exit(1)
" 2>&1 || {
    echo "[$(date)] WARN: Graph API falló, intentando OneDrive como backup..."
    python3 -c "
from src.ingest.onedrive_client import download_moodle_csvs
download_moodle_csvs()
" 2>&1 || {
        echo "[$(date)] ERROR: OneDrive también falló, usando archivos locales"
    }
}
```

### Paso 5: Desplegar al servidor

```bash
# En tu PC local (Windows)
git add src/ingest/graph_mail_reader.py scripts/run_daily_production.sh
git commit -m "Migrar lectura de correos a Graph API (info@duocapital.cl)"
git push

# En el servidor VPS
ssh root@159.203.118.139
cd ~/tecnipro-reportes
git pull
```

### Paso 6: Probar en el servidor

```bash
# En el servidor
cd ~/tecnipro-reportes
source venv/bin/activate
python3 test_graph_module.py
```

Si el test pasa, el sistema está listo para las próximas ejecuciones automáticas.

## Ventajas de Graph API vs Gmail IMAP

1. ✅ **No hay bloqueos**: Microsoft 365 no bloquea correos de Moodle
2. ✅ **Más confiable**: Graph API es oficial de Microsoft
3. ✅ **Mejor filtrado**: OData queries permiten filtros avanzados
4. ✅ **Sin contraseñas de aplicación**: Usa client_credentials (más seguro)
5. ✅ **Escalable**: Mismo sistema que ya usas para enviar correos

## Rollback (si algo falla)

Si después de migrar algo no funciona:

1. **Editar** `scripts/run_daily_production.sh`
2. **Revertir** al código anterior (usar `email_reader.py`)
3. **Configurar Moodle** para volver a enviar a `reportetecnipro@gmail.com`
4. **git commit + push**
5. **git pull en el servidor**

## Archivos del módulo Graph API

```
src/ingest/graph_mail_reader.py    # Módulo principal
test_graph_module.py                # Test del módulo
test_force_new_token.py             # Verificar permisos
test_token_decode.py                # Decodificar token JWT
GRAPH_API_MIGRATION.md              # Este archivo
```

## Próximos pasos (cuando los permisos estén listos)

⏰ **Tiempo estimado de propagación**: Hasta 15-20 minutos desde que se aplicó admin consent

1. ⏳ Esperar propagación de permisos
2. ✅ Ejecutar `python test_force_new_token.py` → Verificar Mail.Read
3. ✅ Ejecutar `python test_graph_module.py` → Probar descarga
4. ✅ Actualizar Moodle → Enviar a info@duocapital.cl
5. ✅ Modificar `run_daily_production.sh` → Usar Graph API
6. ✅ Desplegar al servidor
7. ✅ Probar en el servidor
8. ✅ Esperar próxima ejecución automática (12:15 o 14:00 Chile)

---

**Última actualización**: 2026-02-12 13:15 Chile
**Estado**: Módulo implementado, esperando propagación de permisos Mail.Read
