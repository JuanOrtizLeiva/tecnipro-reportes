"""Cálculos: días, estado A/R/P, riesgo, estado SENCE."""

import logging
from datetime import datetime

import pandas as pd

from src.transform.cleaner import parse_fecha_espanol

logger = logging.getLogger(__name__)


def calcular_campos(df):
    """Agrega todos los campos calculados al DataFrame consolidado.

    Modifica *df* in-place y lo retorna.
    """
    if df.empty:
        logger.warning("DataFrame vacío — calcular_campos retorna sin procesar")
        return df

    # Validar columnas requeridas — crear con defaults si faltan
    required = [
        "Fecha de inicio del curso", "Fecha de finalización del curso",
        "Calificación", "Progreso del estudiante", "N_Ingresos", "IDSence",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("calculator: faltan columnas %s — se crearán con defaults", missing)
        for col in missing:
            if col in ("Calificación", "Progreso del estudiante"):
                df[col] = 0.0
            elif col == "N_Ingresos":
                df[col] = 0
            else:
                df[col] = ""

    hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Parsear fechas ─────────────────────────────────────
    df["fecha_inicio_dt"] = df["Fecha de inicio del curso"].apply(parse_fecha_espanol)
    df["fecha_fin_dt"] = df["Fecha de finalización del curso"].apply(parse_fecha_espanol)

    # Normalizar último acceso a medianoche para cálculo correcto de días
    def parse_y_normalizar(fecha_str):
        dt = parse_fecha_espanol(fecha_str)
        if dt:
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return None

    df["ultimo_acceso_dt"] = df.get("Último acceso al curso", pd.Series(dtype=str)).apply(
        parse_y_normalizar
    )

    # ── Días ───────────────────────────────────────────────
    df["dias_para_termino"] = df["fecha_fin_dt"].apply(
        lambda d: (d - hoy).days if d else None
    )
    df["dias_de_curso"] = df["fecha_inicio_dt"].apply(
        lambda d: (hoy - d).days if d else None
    )
    df["duracion_dias"] = df.apply(
        lambda r: (r["fecha_fin_dt"] - r["fecha_inicio_dt"]).days
        if r["fecha_fin_dt"] and r["fecha_inicio_dt"]
        else None,
        axis=1,
    )
    df["avance_dias"] = df.apply(
        lambda r: r["dias_de_curso"] / r["duracion_dias"]
        if r["duracion_dias"] and r["duracion_dias"] > 0 and r["dias_de_curso"] is not None
        else None,
        axis=1,
    )
    df["dias_sin_ingreso"] = df["ultimo_acceso_dt"].apply(
        lambda d: (hoy - d).days if d else None
    )

    # ── Estado A/R/P ───────────────────────────────────────
    df["estado_participante"] = df.apply(_determinar_estado, axis=1)

    # ── Riesgo ─────────────────────────────────────────────
    df["riesgo"] = df.apply(_evaluar_riesgo, axis=1)

    # ── Estado SENCE ───────────────────────────────────────
    df["estado_sence"] = df.apply(_calcular_estado_sence, axis=1)
    df["cobertura_sence"] = df["IDSence"].apply(
        lambda x: bool(x and str(x).strip() and str(x).strip() not in ("nan", ""))
    )

    # ── Estado del curso ───────────────────────────────────
    df["estado_curso"] = df["dias_para_termino"].apply(_estado_curso)

    logger.info("Campos calculados agregados")
    return df


def _determinar_estado(row):
    """A = Aprobado, R = Reprobado, P = En Proceso."""
    dias_restantes = row.get("dias_para_termino")

    if dias_restantes is not None and dias_restantes < 0:
        # Curso vencido
        calif = row.get("Calificación")
        if pd.notna(calif) and calif >= 4.0:
            return "A"
        return "R"
    # Curso activo
    return "P"


def _evaluar_riesgo(row):
    """alto / medio / bajo / None (curso terminado)."""
    dias_restantes = row.get("dias_para_termino")

    # Curso ya terminado → sin riesgo
    if dias_restantes is not None and dias_restantes < 0:
        return None

    progreso = row.get("Progreso del estudiante", 0) or 0
    dias_sin = row.get("dias_sin_ingreso")

    # Riesgo ALTO: progreso < 30% Y días sin ingreso > 7
    if progreso < 30 and dias_sin is not None and dias_sin > 7:
        return "alto"

    # Riesgo MEDIO: progreso < 50% O días sin ingreso > 5
    if progreso < 50 or (dias_sin is not None and dias_sin > 5):
        return "medio"

    return "bajo"


def _calcular_estado_sence(row):
    """CONECTADO / SIN_CONEXION / NO_APLICA."""
    id_sence = row.get("IDSence", "")
    if not id_sence or str(id_sence).strip() in ("", "nan"):
        return "NO_APLICA"

    n_ingresos = row.get("N_Ingresos", 0) or 0
    if int(n_ingresos) > 0:
        return "CONECTADO"
    return "SIN_CONEXION"


def _estado_curso(dias_restantes):
    """active / expired / expiring."""
    if dias_restantes is None:
        return "active"
    if dias_restantes < 0:
        return "expired"
    if dias_restantes <= 7:
        return "expiring"
    return "active"
