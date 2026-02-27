# SISTEMA ERP DE COBRANZAS — INSTITUTO DE CAPACITACIÓN TECNIPRO
# Instrucciones para Claude Code (CLAUDE.md)

---

## 🎯 OBJETIVO GENERAL

Construir un sistema web de gestión de cobranzas integrado al ecosistema tecnipro-reportes. El sistema debe:

1. **Importar datos del SII**: Descarga automática (Playwright + certificado digital .pfx) y carga manual de CSV del Registro de Compras y Ventas
2. **Gestionar cobranzas**: Seguimiento factura por factura con soporte de pagos parciales, distribución de pagos masivos, y descuento automático de notas de crédito
3. **Asociar clientes reales y cursos**: Vincular cada factura (emitida a una OTIC intermediaria) con el cliente final y curso correspondiente, con catálogo maestro de clientes
4. **Dashboard analítico premium**: Estadísticas de ventas y cobranzas por OTIC, cliente, curso y tendencia temporal
5. **Integración con tecnipro-reportes**: Enlazado desde la página principal, accesible solo para usuarios administradores

---

## 👥 EQUIPO MULTIAGENTE

### 🎯 COORDINADOR GENERAL (Agente Director)
**Rol**: Dirige todo el proyecto. Define la arquitectura, asigna tareas, valida integración entre módulos, y toma decisiones ante conflictos técnicos.

**Responsabilidades**:
- Mapear TODAS las dependencias entre módulos ANTES de codificar
- Definir contratos de datos formales: qué estructura entra y sale de cada módulo (columnas, tipos, formatos)
- Verificar consistencia de nombres de variables, funciones y columnas en TODO el sistema
- Detectar race conditions, conflictos de estado, inconsistencias de datos
- Validar que cada módulo se integra correctamente con el ecosistema tecnipro-reportes existente
- Aprobar el diseño de cada módulo antes de que se codifique
- Después de cada módulo completado, ejecutar revisión de integración cruzada

### 🔍 REVISOR SENIOR (Agente de Calidad)
**Rol**: Revisa TODO el código antes de que se considere terminado. Busca bugs, inconsistencias, vulnerabilidades, código muerto, y problemas de integración.

**Responsabilidades**:
- Revisar cada archivo después de ser creado o modificado
- Verificar que los contratos de datos definidos por el Coordinador se cumplan
- Buscar edge cases: ¿qué pasa si el CSV viene vacío? ¿Si un RUT tiene formato incorrecto? ¿Si el monto es negativo? ¿Si se paga más de lo que se debe?
- Verificar seguridad: inputs sanitizados, SQL injection, XSS, CSRF
- Verificar que el código del nuevo módulo NO rompe el sistema existente (tecnipro-reportes)
- Validar que los cálculos financieros sean correctos (redondeo de pesos chilenos, sin decimales)
- Ejecutar pruebas mentales de flujo completo: desde la carga de CSV hasta la visualización en dashboard

### 💾 INGENIERO DE DATOS (Agente Especialista)
**Rol**: Diseña el modelo de datos, parsea los CSV del SII, implementa la lógica de negocio financiera.

**Conocimiento requerido**:
- Estructura del Registro de Compras y Ventas del SII de Chile
- Tipos de documentos tributarios: Tipo 33 (Factura Electrónica), Tipo 34 (Factura Exenta), Tipo 61 (Nota de Crédito)
- Lógica de asociación automática de notas de crédito a facturas (por campo "Folio Docto. Referencia")
- Cálculo de saldos con pagos parciales
- Formato de montos en pesos chilenos (sin decimales, punto como separador de miles)
- Formato RUT chileno (XX.XXX.XXX-X con dígito verificador)

### 🎨 DISEÑADOR UI/UX PREMIUM (Agente Especialista)
**Rol**: Diseña la interfaz con estándares de aplicación financiera profesional.

**Directrices**:
- Diseño premium institucional, NO infantil, NO extravagante, NO genérico de template
- Paleta de colores: azul institucional oscuro (confianza), gris neutro (profesionalismo), verde para pagado/positivo, ámbar para parcial/pendiente, rojo suave para vencido/anulado
- Tipografía profesional: fuente sans-serif legible (DM Sans, Source Sans Pro, o IBM Plex Sans), monoespaciada para cifras
- Iconografía profesional: usar Lucide Icons o similar, NUNCA emojis como decoración principal
- Semáforo de estados con colores claros y badges/pills con texto
- Tablas financieras con alineación a la derecha para montos, formato $X.XXX.XXX
- Espacio en blanco generoso, jerarquía visual clara, agrupación por proximidad (Gestalt)
- Responsive pero optimizado para desktop (uso principal será en PC)
- Footer: "Sistema de Cobranzas Tecnipro — Acceso restringido a administradores"

### 🔐 INGENIERO DE SEGURIDAD (Agente Especialista)
**Rol**: Garantiza que el módulo financiero sea seguro.

**Responsabilidades**:
- Acceso restringido SOLO a usuarios con rol administrador del sistema tecnipro-reportes
- Certificado digital (.pfx) almacenado de forma segura en el servidor (permisos 600, fuera del webroot)
- Contraseña del certificado en .env, NUNCA en código
- Sanitización de todos los inputs (especialmente campos de observación, nombres de clientes)
- Protección CSRF en todos los formularios POST
- Validación server-side de montos (no confiar solo en el frontend)
- Logs de auditoría: quién registró cada pago, cuándo, desde qué IP

---

## 📁 ESTRUCTURA DEL PROYECTO

El sistema se integra DENTRO del proyecto tecnipro-reportes existente:

```
tecnipro-reportes/
├── src/
│   ├── web/
│   │   ├── routes.py          # (existente) — agregar blueprint de cobranzas
│   │   ├── routes_cobranzas.py # NUEVO — rutas del módulo de cobranzas
│   │   └── templates/
│   │       └── cobranzas/      # NUEVO — templates HTML del módulo
│   │           ├── dashboard.html
│   │           ├── facturas.html
│   │           ├── pagos.html
│   │           ├── clientes.html
│   │           └── importar.html
│   ├── cobranzas/              # NUEVO — lógica de negocio
│   │   ├── __init__.py
│   │   ├── models.py           # Modelos de datos (SQLite)
│   │   ├── csv_parser.py       # Parser de CSV del SII
│   │   ├── payment_engine.py   # Motor de pagos y distribución
│   │   ├── credit_note_engine.py # Motor de notas de crédito
│   │   ├── client_manager.py   # Gestión de catálogo de clientes
│   │   └── stats_engine.py     # Motor de estadísticas
│   └── scraper/                # (existente) — agregar scraper SII
│       └── sii_scraper.py      # NUEVO — descarga automática del SII
├── data/
│   ├── cobranzas.db            # NUEVO — Base de datos SQLite de cobranzas
│   └── sii_csv/                # NUEVO — CSVs descargados/subidos del SII
└── config/
    └── settings.py             # (existente) — agregar config de cobranzas
```

---

## 💾 MODELO DE DATOS (SQLite)

### Tabla: `documentos_sii`
Almacena TODAS las facturas y notas de crédito importadas del SII.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | INTEGER PK | Autoincremental |
| tipo_doc | INTEGER | 33=Factura, 34=Factura Exenta, 61=Nota Crédito |
| tipo_doc_nombre | TEXT | "Factura Electrónica", "Factura Exenta", "Nota de Crédito" |
| tipo_venta | TEXT | "Del Giro", etc. |
| rut_cliente | TEXT | RUT de la OTIC (receptor legal), formato XX.XXX.XXX-X |
| razon_social | TEXT | Razón social de la OTIC |
| folio | INTEGER | Número de folio del documento |
| fecha_docto | DATE | Fecha de emisión |
| fecha_recepcion | DATETIME | Fecha de recepción en el SII |
| fecha_acuse_recibo | DATETIME | Fecha de acuse de recibo (puede ser NULL) |
| monto_exento | INTEGER | Monto exento (pesos chilenos, sin decimales) |
| monto_neto | INTEGER | Monto neto |
| monto_iva | INTEGER | Monto IVA |
| monto_total | INTEGER | Monto total del documento |
| folio_referencia | INTEGER | Folio del doc de referencia (para NC: folio de la factura que anula/modifica) |
| tipo_doc_referencia | INTEGER | Tipo del doc de referencia |
| periodo_tributario | TEXT | "2024-01" (YYYY-MM extraído del nombre del archivo o datos) |
| archivo_origen | TEXT | Nombre del archivo CSV de donde se importó |
| fecha_importacion | DATETIME | Cuándo se importó al sistema |
| **cliente_id** | INTEGER FK | Referencia al cliente real (NULL si no se ha asignado aún) |
| **curso** | TEXT | Nombre del curso asociado (NULL si no se ha asignado aún) |
| **estado** | TEXT | "Pendiente", "Parcial", "Pagada", "Anulada" |
| **saldo_pendiente** | INTEGER | Monto que falta por cobrar (se recalcula automáticamente) |
| UNIQUE(tipo_doc, folio) | | Evita duplicados al reimportar |

### Tabla: `clientes`
Catálogo maestro de clientes reales (no OTICs).

| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | INTEGER PK | Autoincremental |
| nombre | TEXT UNIQUE | Nombre normalizado del cliente (siempre en Título: "Empresa Ejemplo Spa") |
| nombre_busqueda | TEXT | Versión en MAYÚSCULAS sin tildes para búsqueda/deduplicación |
| rut | TEXT | RUT del cliente real (opcional) |
| contacto | TEXT | Nombre de contacto (opcional) |
| email | TEXT | Email de contacto (opcional) |
| telefono | TEXT | Teléfono (opcional) |
| fecha_creacion | DATETIME | Cuándo se creó |
| creado_por | TEXT | Usuario que lo creó |

**REGLA CRÍTICA DE NORMALIZACIÓN DE CLIENTES:**
- Al crear o buscar un cliente, SIEMPRE normalizar: quitar espacios extras, convertir a Título (primera letra mayúscula de cada palabra), quitar tildes para comparación
- Ejemplo: "HOTEL DIEGO DE ALMAGRO" → se guarda como "Hotel Diego De Almagro", se busca como "HOTEL DIEGO DE ALMAGRO"
- Antes de crear un nuevo cliente, SIEMPRE buscar si ya existe uno similar (comparando nombre_busqueda)
- Mostrar sugerencias de clientes existentes cuando el usuario escribe (autocompletado con fuzzy matching)

### Tabla: `pagos`
Registra cada ingreso de dinero (un pago del banco puede distribuirse en varias facturas).

| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | INTEGER PK | Autoincremental |
| fecha_pago | DATE | Fecha del pago/depósito |
| monto_total | INTEGER | Monto total recibido en el banco |
| observacion | TEXT | Campo libre: nro transferencia, detalle, lo que el usuario quiera |
| fecha_registro | DATETIME | Cuándo se registró en el sistema |
| registrado_por | TEXT | Usuario que registró el pago |

### Tabla: `pago_detalle`
Distribución de un pago entre facturas (relación muchos a muchos).

| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | INTEGER PK | Autoincremental |
| pago_id | INTEGER FK | Referencia al pago (tabla pagos) |
| documento_id | INTEGER FK | Referencia a la factura (tabla documentos_sii) |
| monto_aplicado | INTEGER | Monto de este pago asignado a esta factura |
| fecha_aplicacion | DATETIME | Cuándo se aplicó |

### Tabla: `log_auditoria`
Registro de todas las acciones para trazabilidad.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | INTEGER PK | Autoincremental |
| fecha | DATETIME | Cuándo ocurrió |
| usuario | TEXT | Quién lo hizo |
| accion | TEXT | "importar_csv", "registrar_pago", "asignar_cliente", "anular_factura", etc. |
| detalle | TEXT | Descripción en texto libre del cambio |
| ip | TEXT | IP desde donde se hizo |

---

## 📊 ESTRUCTURA DE LOS CSV DEL SII

### Formato
- Separador: `;` (punto y coma)
- Encoding: probable Latin-1 o UTF-8 (verificar ambos)
- Primera fila: encabezados

### Columnas del CSV (Registro de Ventas del SII)
```
Nro;Tipo Doc;Tipo Venta;Rut cliente;Razon Social;Folio;Fecha Docto;Fecha Recepcion;
Fecha Acuse Recibo;Fecha Reclamo;Monto Exento;Monto Neto;Monto IVA;Monto total;
IVA Retenido Total;IVA Retenido Parcial;IVA no retenido;IVA propio;IVA Terceros;
RUT Emisor Liquid. Factura;Neto Comision Liquid. Factura;Exento Comision Liquid. Factura;
IVA Comision Liquid. Factura;IVA fuera de plazo;Tipo Docto. Referencia;Folio Docto. Referencia;
...
```

### Tipos de Documento relevantes
| Tipo Doc | Nombre | Tratamiento |
|----------|--------|-------------|
| 33 | Factura Electrónica | Genera cuenta por cobrar |
| 34 | Factura Electrónica Exenta | Genera cuenta por cobrar |
| 61 | Nota de Crédito Electrónica | Reduce/anula cuenta por cobrar |

### Formatos de fecha detectados (¡OJO! varían entre archivos)
- Formato 1: `03-01-2023` (DD-MM-YYYY)
- Formato 2: `02/01/2024` (DD/MM/YYYY)
- El parser DEBE detectar y manejar ambos formatos automáticamente

### Nombre de archivos
- Patrón: `MM_YYYY.csv` (ejemplo: `01_2023.csv`, `06_2024.csv`)
- De aquí se extrae el período tributario

### OTICs conocidas (receptores frecuentes)
Algunas razón sociales que aparecen son OTICs/intermediarios, no clientes finales:
- CORP DE CAPACITACION Y EMPLEO DE SOC DE FOMENTO FABRIL (SOFOFA)
- CORP DE CAPACITACION DE LA CONSTRUCCION (CChC)
- ASOC CHILENA DE SEGURIDAD (ACHS)
- Y otras que el sistema irá identificando

---

## 🔄 FLUJOS FUNCIONALES

### FLUJO 1: Importación de CSV
1. Usuario va a la sección "Importar Datos"
2. Puede arrastrar/seleccionar uno o más archivos CSV
3. El sistema parsea cada archivo:
   - Detecta el período tributario desde el nombre del archivo
   - Parsea cada fila según el tipo de documento
   - Normaliza fechas (ambos formatos)
   - Normaliza RUTs
   - Detecta duplicados (por tipo_doc + folio) y los omite con aviso
4. Muestra resumen pre-importación:
   - Cantidad de facturas nuevas
   - Cantidad de notas de crédito nuevas
   - Cantidad de duplicados omitidos
   - Monto total a importar
5. Usuario confirma → se insertan en la BD
6. Las notas de crédito se asocian automáticamente a sus facturas (via folio_referencia) y ajustan el saldo_pendiente
7. Se registra en log_auditoria

### FLUJO 2: Descarga automática del SII (Fase 2 — Playwright)
1. Cron job mensual o botón manual
2. Autenticación al SII con certificado digital .pfx
3. Navegación al Registro de Compras y Ventas
4. Descarga del CSV del período seleccionado
5. Procesamiento automático igual que Flujo 1
6. Notificación de resultado

**NOTA**: Este flujo se implementa DESPUÉS de que el flujo manual esté 100% funcional. El patrón a seguir es el mismo del scraper SENCE existente en `src/scraper/`.

### FLUJO 3: Registro de Pago (CRÍTICO — diseñar con mucho cuidado)
1. Usuario va a "Registrar Pago"
2. Ingresa:
   - **Fecha del pago** (datepicker)
   - **Monto total recibido** (el monto que aparece en la cartola bancaria)
   - **Observación** (campo libre: nro transferencia, banco, detalle)
3. El sistema muestra la lista de facturas pendientes/parciales
4. El usuario **distribuye el monto** entre las facturas:
   - Puede seleccionar facturas y asignar montos individuales
   - El sistema muestra en tiempo real:
     - Monto total del pago
     - Monto distribuido hasta ahora
     - Monto sin distribuir (diferencia)
   - **Validación**: la suma de los montos distribuidos NO puede exceder el monto total del pago
   - **Validación**: el monto asignado a una factura NO puede exceder su saldo pendiente
5. Al confirmar:
   - Se crea el registro en `pagos`
   - Se crean los registros en `pago_detalle`
   - Se actualiza el `saldo_pendiente` de cada factura afectada
   - Se actualiza el `estado` de cada factura:
     - Si saldo_pendiente == 0 → "Pagada"
     - Si saldo_pendiente > 0 y tiene al menos un pago → "Parcial"
     - Si no tiene pagos → "Pendiente"
   - Se registra en log_auditoria

**EJEMPLO CONCRETO:**
```
Depósito bancario: $10.000.000
Observación: "Transferencia BancoEstado ref 84729183"

Distribución:
├── Factura 1580 (OTIC SOFOFA) - Total $4.000.000, Saldo $4.000.000 → Asignar $4.000.000 → Queda Pagada
├── Factura 1582 (OTIC CChC)   - Total $5.000.000, Saldo $5.000.000 → Asignar $3.500.000 → Queda Parcial ($1.500.000 pendiente)
└── Factura 1585 (OTIC ACHS)   - Total $3.000.000, Saldo $3.000.000 → Asignar $2.500.000 → Queda Parcial ($500.000 pendiente)

Total distribuido: $10.000.000 ✅ (cuadra con el depósito)
```

### FLUJO 4: Asignación de Cliente Real y Curso
1. En la vista de facturas, cada fila tiene campos editables:
   - **Cliente**: campo con autocompletado (dropdown) que busca en el catálogo de clientes
     - Al escribir, muestra sugerencias de clientes existentes (fuzzy matching)
     - Opción "Crear nuevo cliente" al final de la lista
     - Al crear nuevo: normaliza automáticamente (quita espacios extras, formato Título)
     - ANTES de crear, verifica si ya existe uno similar y advierte: "¿Quisiste decir 'Hotel Diego De Almagro'?"
   - **Curso**: campo de texto libre con autocompletado de cursos previamente usados
2. Los cambios se guardan inmediatamente (inline editing, sin necesidad de botón guardar)
3. Se registra en log_auditoria

### FLUJO 5: Notas de Crédito
1. Al importar una nota de crédito (Tipo Doc 61):
   - Si tiene `Folio Docto. Referencia`, buscar la factura original por ese folio
   - Si la encuentra: restar el monto de la NC del saldo_pendiente de la factura
   - Si el saldo queda en 0 o negativo → estado "Anulada"
   - Si no encuentra la factura referenciada → marcar NC como "sin asociar" para revisión manual
2. Mostrar las NC asociadas en el historial de cada factura (igual que los pagos)

---

## 📊 DASHBOARD Y VISTAS

### Vista 1: Dashboard Principal de Cobranzas
**3 pestañas:**

**Pestaña A — "Ventas Históricas" (todos los años):**
- Barras de facturación anual (comparativo de todos los años disponibles)
- Línea de tendencia de ventas mensuales
- Facturación por OTIC (tabla + gráfico, todos los años)
- Cantidad de facturas emitidas por período
- Resumen: total facturado histórico, promedio mensual, año con más ventas

**Pestaña B — "Cobranzas Activas" (solo 2026+):**
- KPIs en cards: Total facturado, Total cobrado, Total pendiente, % recuperación, Facturas pendientes, Días promedio de cobro
- Torta/donut de estados (Pendiente, Parcial, Pagada, Anulada) con semáforo
- Barras de cobranza mensual vs facturación (comparativo mes a mes)
- Top 5 OTICs por monto pendiente
- Alertas: facturas con más de 30/60/90 días sin pago

**Pestaña C — "Análisis por Cliente y Curso" (solo 2026+):**
- Top clientes reales por facturación (tabla + gráfico)
- Top cursos por facturación (tabla + gráfico)
- Matriz cliente × curso (qué clientes compraron qué cursos)
- Facturación por cliente con detalle de estado de pago
- Tendencia mensual por cliente

### Vista 2: Listado de Facturas
**Tabla interactiva con:**
- Columnas: Folio, Fecha, OTIC (Razón Social), Cliente Real, Curso, Monto Total, NC Aplicadas, Pagos Realizados, Saldo Pendiente, Estado (badge con color)
- Filtros: por OTIC, por estado, por rango de fechas, por período tributario. Filtros por cliente y curso solo disponibles para facturas 2026+
- Búsqueda global
- Ordenamiento por cualquier columna
- **Facturas 2026+**: columnas Cliente Real y Curso son editables (inline), se puede registrar pagos
- **Facturas 2025 y anteriores**: columnas Cliente Real y Curso muestran "—" (no editables), estado fijo "Pagada", sin botón de registrar pago
- Al hacer clic en una factura → detalle expandido mostrando:
  - Datos completos del documento SII
  - Notas de crédito asociadas (con monto y folio)
  - Historial de pagos: cada abono con fecha, monto, observación, quién lo registró (solo 2026+)
  - Campos editables: cliente y curso (solo 2026+)

### Vista 3: Registro de Pagos
- Formulario de registro de pago (Flujo 3 descrito arriba)
- Lista de pagos recientes con opción de ver detalle de distribución
- Cada pago muestra: fecha, monto total, observación, y desglose de facturas a las que se aplicó

### Vista 4: Gestión de Clientes
- Lista de clientes con cantidad de facturas y monto total facturado
- Edición de datos de cliente
- Merge de clientes duplicados (seleccionar 2 clientes → unificar en uno)
- Estadísticas por cliente: total facturado, total pagado, cursos realizados

### Vista 5: Importar Datos
- Zona de drag & drop para CSV
- Historial de importaciones
- Opción de descarga automática del SII (cuando esté implementado)
- Panel de validación: qué períodos ya están importados y cuáles faltan

### Vista 6: Estadísticas Avanzadas
**Históricas (todos los años):**
- Facturación por OTIC (tabla + gráfico)
- Tendencia temporal: evolución de ventas mensuales (línea)
- Comparativo año actual vs años anteriores
- Cantidad de documentos por tipo (facturas, exentas, NC)

**Gestión activa (solo 2026+):**
- Facturación por cliente real (tabla + gráfico)
- Facturación por curso (tabla + gráfico)
- Análisis de cobranza: días promedio de cobro por OTIC
- Estado de cartera: distribución de montos por estado
- Ranking de clientes por puntualidad de pago

---

## 🎨 DIRECTRICES DE DISEÑO PREMIUM

### Filosofía
**Aplicación financiera institucional.** Piensa en un sistema de banca corporativa o un ERP financiero profesional. NO un template de admin genérico. Cada elemento debe transmitir confianza, precisión y seriedad.

### Paleta de Colores
```css
:root {
  /* Base institucional */
  --primary: #1a365d;        /* Azul oscuro — confianza, autoridad */
  --primary-light: #2c5282;  /* Azul medio */
  --primary-lighter: #ebf4ff; /* Azul muy claro para fondos */
  
  /* Neutros */
  --bg-main: #f7f8fc;        /* Fondo principal — gris muy sutil azulado */
  --bg-card: #ffffff;         /* Fondo de cards */
  --text-primary: #1a202c;   /* Texto principal */
  --text-secondary: #718096;  /* Texto secundario */
  --border: #e2e8f0;         /* Bordes */
  
  /* Semáforo de estados */
  --estado-pendiente: #e53e3e;  /* Rojo — urgencia */
  --estado-parcial: #d69e2e;    /* Ámbar — en proceso */
  --estado-pagada: #38a169;     /* Verde — completado */
  --estado-anulada: #a0aec0;    /* Gris — inactivo */
  
  /* Montos */
  --monto-positivo: #276749;  /* Verde oscuro para ingresos */
  --monto-negativo: #9b2c2c;  /* Rojo oscuro para descuentos/NC */
}
```

### Tipografía
- Títulos y navegación: "DM Sans" (Google Fonts) — moderna, profesional
- Cuerpo: "DM Sans" regular
- Montos/cifras: "JetBrains Mono" o "IBM Plex Mono" — monoespaciada para alineación perfecta de cifras
- Tamaños: jerarquía clara (32px títulos → 14px cuerpo → 12px captions)

### Iconografía
- Usar **Lucide Icons** (ya disponible en el stack)
- Iconos monocromáticos, sutiles, profesionales
- NO usar iconos coloridos, NO usar emojis como iconos funcionales
- Ejemplos: FileText para facturas, CreditCard para pagos, Users para clientes, BarChart3 para estadísticas, Upload para importar

### Componentes UI
- **Cards KPI**: fondo blanco, borde sutil, icono a la izquierda, número grande, label pequeño abajo
- **Tablas**: header con fondo azul oscuro y texto blanco, filas alternas con zebra sutil, hover con fondo azul clarísimo
- **Badges de estado**: pill/badge con fondo del color del estado y texto contrastante
- **Formularios**: inputs con borde fino, focus con borde azul, labels arriba del input
- **Botones**: primario en azul oscuro, secundario en borde, destructivo en rojo suave
- **Navegación**: sidebar o tabs superiores con iconos + texto
- **Gráficos**: Chart.js con la paleta de colores del sistema, sin grid lines excesivos, tooltips limpios

### Formato de Datos Financieros
- Montos: **$1.234.567** (peso chileno, punto como separador de miles, SIN decimales)
- Porcentajes: **85,3%** (coma decimal)
- RUT: **12.345.678-9** (formato estándar con puntos y guión)
- Fechas: **26 Feb 2026** o **26/02/2026** según contexto
- Todos los montos alineados a la DERECHA en tablas

---

## ⚙️ REQUISITOS TÉCNICOS

### Stack
- **Backend**: Flask (mismo que tecnipro-reportes) con Blueprint separado para cobranzas
- **Base de datos**: SQLite (archivo `data/cobranzas.db`)
- **Frontend**: HTML + CSS + JavaScript vanilla (sin frameworks pesados)
- **Gráficos**: Chart.js (ya usado en tecnipro-reportes)
- **Iconos**: Lucide Icons (CDN o inline SVG)
- **Scraper SII**: Playwright (mismo patrón que scraper SENCE existente)
- **Certificado digital**: .pfx almacenado en ruta segura del servidor

### Integración con tecnipro-reportes
- Registrar el Blueprint en la app Flask principal
- Agregar enlace en la navegación principal (solo visible para administradores)
- Usar el mismo sistema de autenticación y sesiones existente
- Compartir el layout base (header, sidebar, footer) del sistema existente
- No duplicar CSS/JS: extender los estilos existentes

### Seguridad
- Decorador `@admin_required` en TODAS las rutas de cobranzas
- CSRF token en todos los formularios
- Sanitización de inputs (especialmente campo observación y nombres de clientes)
- Certificado .pfx con permisos 600 (solo root puede leer)
- Contraseña del certificado en .env como `SII_CERT_PASSWORD`
- Path del certificado en .env como `SII_CERT_PATH`

### Configuración (.env — agregar estas variables)
```
# SII - Certificado Digital
SII_CERT_PATH=/etc/ssl/private/tecnipro.pfx
SII_CERT_PASSWORD=tu_contraseña_del_certificado
SII_RUT_EMPRESA=75620735-K
SII_AMBIENTE=produccion

# Cobranzas
COBRANZAS_DB_PATH=data/cobranzas.db
```

---

## 🚀 PLAN DE EJECUCIÓN (por fases)

### FASE 1: Fundamentos (Coordinador + Ingeniero de Datos)
1. Crear estructura de carpetas y archivos
2. Crear base de datos SQLite con todas las tablas
3. Implementar csv_parser.py (parser robusto de CSV del SII)
4. Implementar models.py (CRUD de todas las tablas)
5. **REVISIÓN**: Revisor valida modelo de datos y parser

### FASE 2: Motor de Negocio (Ingeniero de Datos + Revisor)
1. Implementar credit_note_engine.py (asociación automática de NC)
2. Implementar payment_engine.py (registro y distribución de pagos)
3. Implementar client_manager.py (catálogo con normalización y deduplicación)
4. Implementar stats_engine.py (cálculos de estadísticas)
5. **REVISIÓN**: Revisor valida lógica financiera, edge cases, cálculos

### FASE 3: Interfaz Web (Diseñador + Coordinador)
1. Crear Blueprint Flask con rutas
2. Implementar vista de Importación (upload + validación + confirmación)
3. Implementar vista de Facturas (listado + detalle + inline editing)
4. Implementar vista de Registro de Pagos (formulario + distribución)
5. Implementar vista de Clientes (catálogo + autocompletado + merge)
6. Implementar Dashboard principal (KPIs + gráficos)
7. Implementar Estadísticas avanzadas
8. **REVISIÓN**: Revisor valida UI, responsividad, UX, seguridad

### FASE 4: Integración (Coordinador + Revisor)
1. Integrar Blueprint en app Flask principal de tecnipro-reportes
2. Agregar enlace en navegación (solo admin)
3. Verificar que NO rompe nada del sistema existente
4. Probar flujo completo: importar CSV → asignar clientes → registrar pagos → ver estadísticas
5. **REVISIÓN FINAL**: Revisor ejecuta checklist completo

### FASE 5 (FUTURA): Scraper SII
1. Implementar sii_scraper.py con Playwright
2. Autenticación con certificado digital
3. Navegación y descarga de CSV
4. Integración con cron job
5. **REVISIÓN**: Seguridad del manejo del certificado

---

## ⚠️ REGLAS CRÍTICAS

1. **NUNCA modificar archivos existentes de tecnipro-reportes sin verificar impacto** — Cualquier cambio a routes.py, settings.py, o templates existentes debe ser mínimo y no romper funcionalidad actual
2. **Los montos son SIEMPRE enteros** — Pesos chilenos no tienen decimales. Usar INTEGER en la BD, nunca FLOAT
3. **La normalización de clientes es OBLIGATORIA** — Nunca crear un cliente sin antes buscar duplicados
4. **Cada pago debe cuadrar** — La suma de distribuciones DEBE ser igual al monto total del pago. NUNCA permitir descuadres
5. **El saldo pendiente se RECALCULA** — Después de cada pago o NC, recalcular: saldo = monto_total - sum(pagos) - sum(notas_credito)
6. **Log de auditoría en TODA acción financiera** — Importación, pago, asignación, anulación, edición de cliente
7. **Commits por fase** — Hacer commit al terminar cada fase con mensaje descriptivo
8. **NO empezar la Fase 5 (scraper SII) hasta que Fases 1-4 estén completas y probadas**

---

## 📌 REGLAS DE NEGOCIO CRÍTICAS (CORTE TEMPORAL)

### Regla 1: Datos históricos (2025 y anteriores) = SOLO estadísticas de venta
- Todas las facturas de **2025 hacia atrás** se importan con estado **"Pagada"** automáticamente (saldo_pendiente = 0)
- NO se les asigna cliente real ni curso (campos quedan NULL)
- Las notas de crédito históricas SÍ se aplican normalmente (reducen el monto facturado para estadísticas correctas)
- Estos datos sirven SOLO para: tendencia de ventas por año/mes, cantidad de facturas en el tiempo, facturación por OTIC, comparativos anuales

### Regla 2: Datos activos (2026 en adelante) = Gestión completa
- Las facturas de **2026 en adelante** son las únicas que reciben gestión de cobranza activa
- SOLO estas facturas permiten: asignar cliente real, asignar curso, registrar pagos, estados de semáforo
- El estado inicial al importar es **"Pendiente"** (a diferencia de las históricas que entran como "Pagada")

### Regla 3: Separación en el Dashboard
- **Pestaña "Ventas Históricas"**: Gráficos de tendencia de venta por año, comparativo anual, facturación por OTIC (incluye TODOS los años)
- **Pestaña "Cobranzas Activas"**: KPIs de cobranza, estados de facturas, pagos pendientes (SOLO 2026+)
- **Pestaña "Análisis por Cliente y Curso"**: Facturación por cliente real, por curso, rendimiento por cliente (SOLO 2026+ donde hay datos de cliente/curso)

### Regla 4: Interfaz condicionada por año
- En el listado de facturas, las columnas "Cliente Real" y "Curso" solo son **editables** para facturas 2026+
- Para facturas históricas, esas columnas muestran "—" (guión) y no son clickeables
- El filtro por cliente y por curso solo aplica a facturas 2026+
- El botón "Registrar Pago" solo aparece para facturas 2026+ con estado Pendiente o Parcial

### Implementación técnica del corte temporal
```python
ANIO_CORTE_GESTION = 2026  # Año desde el cual se gestiona cobranza activa

def estado_inicial_por_fecha(fecha_docto):
    """Determina el estado inicial de una factura al importarla."""
    if fecha_docto.year < ANIO_CORTE_GESTION:
        return "Pagada"  # Histórico: se asume cobrado
    return "Pendiente"    # Activo: requiere gestión

def permite_gestion(factura):
    """Determina si una factura permite asignación de cliente/curso/pagos."""
    return factura.fecha_docto.year >= ANIO_CORTE_GESTION
```

---

## 📋 DATOS INICIALES PARA PRUEBAS

Se entregarán CSVs del SII de los últimos años. El sistema debe poder importar todos los meses disponibles y construir el histórico completo. Los archivos siguen el patrón `MM_YYYY.csv`.

El sistema debe funcionar correctamente con:
- Archivos de diferentes años con formatos de fecha distintos
- Facturas exentas (tipo 34) — no tienen IVA
- Notas de crédito (tipo 61) que referencian facturas
- Razones sociales con caracteres especiales (tildes, Ñ, etc.)
- RUTs con K como dígito verificador
