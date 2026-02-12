# Configuración Email IMAP - Reportes Moodle

## Descripción

El sistema ahora puede recibir los archivos Moodle (Greporte.csv y Dreporte.csv) directamente por email vía IMAP, en lugar de depender exclusivamente de OneDrive.

**Arquitectura de redundancia:**
1. **Primario**: Email IMAP (Gmail)
2. **Backup**: OneDrive/SharePoint (si email falla)
3. **Fallback**: Archivos locales

## Configuración Inicial

### 1. Credenciales de Email

Ya tienes creado el correo: `reportetecnipro@gmail.com` con su App Password.

### 2. Actualizar archivo `.env`

Edita tu archivo `.env` (en el servidor VPS) y agrega/actualiza estas líneas:

```bash
# Email IMAP — para recibir archivos Moodle directo por email
EMAIL_MOODLE_USER=reportetecnipro@gmail.com
EMAIL_MOODLE_PASSWORD=TU_APP_PASSWORD_AQUI
EMAIL_MOODLE_FROM=noreply@virtual.institutotecnipro.cl
IMAP_SERVER=imap.gmail.com
```

**IMPORTANTE:** Reemplaza `TU_APP_PASSWORD_AQUI` con el App Password que generaste en Gmail (16 caracteres sin espacios).

### 3. Configurar Moodle para enviar a este email

Actualiza la configuración de Moodle para que envíe los reportes automáticos a:
- **Destinatario:** `reportetecnipro@gmail.com`

Puedes mantener también el envío a Power Automate como backup.

### 4. Reiniciar servicios en el servidor

Después de actualizar el `.env`, reinicia los servicios:

```bash
# SSH al servidor
ssh tecnipro@tu-servidor-ip

# Reiniciar servicio web
sudo systemctl restart tecnipro-web

# Probar pipeline manualmente
cd ~/tecnipro-reportes
source venv/bin/activate
python -m src.main --scrape --report --email
```

## Cómo Funciona

### Filtros de Seguridad

El sistema aplica **múltiples filtros** para asegurar que solo procesa emails legítimos de Moodle:

1. **Filtro de Remitente (FROM)**
   - Solo emails de: `noreply@virtual.institutotecnipro.cl`
   - Ignora emails de otras fuentes (spam, notificaciones de Google, etc.)

2. **Filtro de Asunto (SUBJECT)**
   - Email 1: "Control de cursos Asincrónicos y Sincrónicos" → Greporte.csv
   - Email 2: "Reporte Asincronico" → Dreporte.csv
   - Ignora emails con asuntos no reconocidos

3. **Filtro de Estado (UNSEEN)**
   - Solo emails no leídos
   - Marca como leído después de procesar (evita duplicados)

4. **Filtro de Adjuntos**
   - Solo archivos .csv nombrados "Greporte.csv" o "Dreporte.csv"
   - Ignora otros adjuntos

**Resultado:** El sistema **solo descarga archivos de emails legítimos de Moodle**, ignorando cualquier otro correo que llegue a la bandeja.

### Flujo de Descarga

El script `run_daily_production.sh` ahora ejecuta:

1. **Intenta descargar desde Email (IMAP)**
   - Conecta a `imap.gmail.com`
   - Busca emails no leídos
   - Descarga adjuntos `Greporte.csv` y `Dreporte.csv`
   - Marca emails como leídos
   - ✅ Si encuentra ambos archivos → continúa

2. **Si falla Email → intenta OneDrive**
   - Descarga desde SharePoint usando Microsoft Graph API
   - ✅ Si encuentra archivos → continúa

3. **Si ambos fallan → usa archivos locales**
   - Usa los últimos archivos descargados en `data/`
   - ⚠️ Genera alerta (datos pueden estar desactualizados)

### Logs

Los logs del sistema están en:
- **Web**: `/var/log/tecnipro/web.log`
- **Pipeline diario**: `/var/log/tecnipro/daily.log`

Para ver logs en tiempo real:
```bash
sudo tail -f /var/log/tecnipro/daily.log
```

## Ventajas de Email vs OneDrive

| Característica | Email IMAP | OneDrive |
|----------------|------------|----------|
| **Velocidad** | ⚡ Rápido (conexión directa) | 🐢 Lento (Graph API) |
| **Simplicidad** | ✅ Simple (IMAP estándar) | ⚠️ Complejo (OAuth, tokens) |
| **Costo** | 💰 Gratis (Gmail) | 💰 Gratis (pero requiere Azure AD) |
| **Confiabilidad** | ✅ Alta | ✅ Alta |
| **Dependencias** | 📧 Solo Gmail | ☁️ Microsoft 365 + Azure |

## Troubleshooting

### Email no se descarga

1. **Verificar credenciales:**
   ```bash
   cd ~/tecnipro-reportes
   source venv/bin/activate
   python3 -c "
   from src.ingest.email_reader import descargar_adjuntos_moodle
   resultado = descargar_adjuntos_moodle()
   print(resultado)
   "
   ```

2. **Verificar que Gmail permite IMAP:**
   - Ir a Gmail → Settings → Forwarding and POP/IMAP
   - Asegurar que "IMAP access" está habilitado

3. **Verificar App Password:**
   - El App Password es de 16 caracteres sin espacios
   - Asegurar que no tiene saltos de línea en el `.env`

### OneDrive tampoco funciona

Si ambos métodos fallan:
1. Verificar que los archivos existen en `data/Greporte.csv` y `data/Dreporte.csv`
2. Revisar logs: `sudo tail -100 /var/log/tecnipro/daily.log`
3. Ejecutar pipeline manualmente para ver errores en tiempo real

### Emails se acumulan sin descargar

El sistema marca emails como leídos después de procesarlos. Si se acumulan:
1. Revisar que el timer diario está funcionando: `systemctl status tecnipro-daily.timer`
2. Verificar última ejecución: `systemctl list-timers --all | grep tecnipro`

## Seguridad

- ✅ App Password (no contraseña real de Gmail)
- ✅ Conexión IMAP sobre SSL/TLS
- ✅ Credenciales en `.env` (no en código)
- ✅ `.env` en `.gitignore` (nunca se sube a Git)
- ✅ Permisos restrictivos en servidor: `chmod 600 .env`

## Mantenimiento

### Rotar App Password

Si necesitas cambiar el App Password:
1. Gmail → Security → App Passwords → Revoke
2. Crear nuevo App Password
3. Actualizar `.env` con nuevo password
4. Reiniciar servicios: `sudo systemctl restart tecnipro-web`

### Monitorear uso de Gmail

Gmail tiene límites de IMAP:
- **Descarga**: Sin límite práctico para 2 archivos/día
- **Conexiones**: Máximo ~500 conexiones/día

El pipeline se ejecuta 1 vez/día (L-V), así que estamos muy por debajo del límite.
