"""Schema formal: columnas esperadas entre módulos del pipeline.

Este archivo documenta los CONTRATOS de datos entre las capas
ingest → transform → output. Si un módulo upstream cambia las columnas
que produce, este archivo indica qué módulos downstream se romperán.

Uso:
    from src.transform.schema import MERGED_BASE_COLUMNS, SENCE_COLUMNS
"""

# ── Columnas que produce moodle_api_reader / merge_greporte_dreporte ──
# Estas son las columnas mínimas que merger.py y calculator.py esperan.
MERGED_BASE_COLUMNS = [
    "nombre_curso",
    "nombre_corto",
    "Nombre completo Participante",
    "ID del Usuario",
    "Dirección de correo",
    "Fecha de inicio del curso",
    "Fecha de finalización del curso",
    "Último acceso al curso",
    "Progreso del estudiante",       # float 0-100
    "Calificación",                  # float o None
    "IDSence",                       # str, puede ser ""
    "LLave",                         # str: IDUser+IDSence, "" si no hay IDSence
    "Modalidad",                     # "Asincrónico" / "Sincrónico" / ""
    "categoria",
]

# ── Columnas opcionales (solo modo API) ──
API_ONLY_COLUMNS = [
    "Evaluaciones Rendidas",         # int
    "Total Evaluaciones",            # int
    "Promedio Evaluadas",            # float o None
    "Resumen Evaluaciones",          # str "3/5"
]

# ── Columnas que produce sence_reader.leer_sence() ──
SENCE_COLUMNS = [
    "LLave",         # str: IDUser + IDSence (clave de merge)
    "IDUser",        # str: RUT normalizado
    "IDSence",       # str: ID SENCE del curso
    "N_Ingresos",    # int: conteo de sesiones
    "DJ",            # str: estado declaración jurada
]

# ── Columnas que produce compradores_reader.leer_compradores() ──
COMPRADORES_COLUMNS = [
    "id_curso_moodle",   # str: clave de merge con nombre_corto
    "comprador_nombre",  # str
    "empresa",           # str
    "email_comprador",   # str
]

# ── Columnas que agrega merger.merge_sence_into_dreporte() ──
SENCE_MERGE_ADDS = ["N_Ingresos", "DJ"]

# ── Columnas que agrega merger.merge_compradores() ──
COMPRADORES_MERGE_ADDS = ["comprador_nombre", "empresa", "email_comprador"]

# ── Columnas que agrega calculator.calcular_campos() ──
CALCULATOR_ADDS = [
    "fecha_inicio_dt",       # datetime
    "fecha_fin_dt",          # datetime
    "ultimo_acceso_dt",      # datetime
    "dias_para_termino",     # int o None
    "dias_de_curso",         # int o None
    "duracion_dias",         # int o None
    "avance_dias",           # float o None
    "dias_sin_ingreso",      # int o None
    "estado_participante",   # "A" / "R" / "P"
    "riesgo",                # "alto" / "medio" / "bajo" / None
    "estado_sence",          # "CONECTADO" / "SIN_CONEXION" / "NO_APLICA"
    "cobertura_sence",       # bool
    "estado_curso",          # "active" / "expired" / "expiring"
]

# ── Columnas que json_exporter lee del DataFrame final ──
# (todas las anteriores combinadas)
JSON_EXPORTER_READS = (
    MERGED_BASE_COLUMNS
    + API_ONLY_COLUMNS
    + SENCE_MERGE_ADDS
    + COMPRADORES_MERGE_ADDS
    + CALCULATOR_ADDS
)
