"""Cruce de las 3 fuentes de datos + compradores."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def merge_sence_into_dreporte(df_dreporte, df_sence):
    """LEFT JOIN del Dreporte con los datos SENCE usando la columna LLave.

    Agrega columnas: N_Ingresos, DJ al Dreporte.
    """
    # Verificar columna clave en dreporte
    if "LLave" not in df_dreporte.columns:
        logger.warning("Dreporte no tiene columna 'LLave' — SENCE no se puede cruzar")
        df_dreporte["N_Ingresos"] = 0
        df_dreporte["DJ"] = ""
        return df_dreporte

    if df_sence.empty:
        df_dreporte["N_Ingresos"] = 0
        df_dreporte["DJ"] = ""
        logger.info("SENCE vacío — se agregaron columnas con valores por defecto")
        return df_dreporte

    # Verificar columnas requeridas en SENCE
    required_sence = ["LLave", "N_Ingresos", "DJ"]
    missing = [c for c in required_sence if c not in df_sence.columns]
    if missing:
        logger.warning("SENCE falta columnas %s — merge omitido", missing)
        df_dreporte["N_Ingresos"] = 0
        df_dreporte["DJ"] = ""
        return df_dreporte

    # Preparar SENCE para merge (solo columnas necesarias, sin duplicados)
    sence_para_merge = (
        df_sence[["LLave", "N_Ingresos", "DJ"]]
        .drop_duplicates(subset=["LLave"], keep="first")
        .copy()
    )

    resultado = df_dreporte.merge(
        sence_para_merge,
        on="LLave",
        how="left",
        suffixes=("", "_sence"),
    )

    # Rellenar NaN en columnas SENCE
    resultado["N_Ingresos"] = resultado["N_Ingresos"].fillna(0).astype(int)
    resultado["DJ"] = resultado["DJ"].fillna("")

    # Quitar columna Estado (del Dreporte)
    if "Estado" in resultado.columns:
        resultado = resultado.drop(columns=["Estado"])

    logger.info(
        "Merge SENCE→Dreporte: %d filas, %d con datos SENCE",
        len(resultado),
        (resultado["N_Ingresos"] > 0).sum(),
    )
    return resultado


def merge_greporte_dreporte(df_greporte, df_dreporte):
    """FULL OUTER JOIN entre Greporte y Dreporte procesado.

    Clave: Greporte."Nombre corto del curso" = Dreporte."Nombre corto del curso con enlace"
    """
    # Eliminar columnas redundantes de Greporte que colisionan con Dreporte
    # para evitar sufijos ambiguos en el merge
    greporte_clean = df_greporte.drop(
        columns=[
            c for c in ["Nombre corto del curso con enlace"]
            if c in df_greporte.columns
        ]
    ).copy()

    resultado = df_dreporte.merge(
        greporte_clean,
        left_on="Nombre corto del curso con enlace",
        right_on="Nombre corto del curso",
        how="outer",
        suffixes=("_d", "_g"),
    )

    # Consolidar nombre completo del curso: preferir Greporte, fallback Dreporte
    col_nombre_g = "Nombre completo del curso"
    col_nombre_d = "Nombre completo del curso con enlace"

    if col_nombre_g in resultado.columns and col_nombre_d in resultado.columns:
        resultado["nombre_curso"] = resultado[col_nombre_g].fillna(
            resultado[col_nombre_d]
        )
    elif col_nombre_g in resultado.columns:
        resultado["nombre_curso"] = resultado[col_nombre_g]
    elif col_nombre_d in resultado.columns:
        resultado["nombre_curso"] = resultado[col_nombre_d]
    else:
        resultado["nombre_curso"] = ""

    # Consolidar nombre corto del curso
    resultado["nombre_corto"] = resultado[
        "Nombre corto del curso con enlace"
    ].fillna(resultado.get("Nombre corto del curso", pd.Series(dtype=str)))

    # Consolidar fechas: preferir Greporte
    for campo_base in ["Fecha de inicio del curso", "Fecha de finalización del curso"]:
        col_g = f"{campo_base}_g" if f"{campo_base}_g" in resultado.columns else campo_base
        col_d = f"{campo_base}_d" if f"{campo_base}_d" in resultado.columns else None

        if col_g in resultado.columns and col_d and col_d in resultado.columns:
            resultado[campo_base] = resultado[col_g].fillna(resultado[col_d])
        elif col_g in resultado.columns:
            resultado[campo_base] = resultado[col_g]

    # Consolidar categoría
    if "Nombre de la categoría_g" in resultado.columns:
        resultado["categoria"] = resultado["Nombre de la categoría_g"].fillna(
            resultado.get("Nombre de la categoría_d", "")
        )
    elif "Nombre de la categoría_d" in resultado.columns:
        resultado["categoria"] = resultado["Nombre de la categoría_d"]
    elif "Nombre de la categoría" in resultado.columns:
        resultado["categoria"] = resultado["Nombre de la categoría"]
    else:
        resultado["categoria"] = ""

    logger.info("Merge Greporte⊕Dreporte: %d filas", len(resultado))
    return resultado


def merge_compradores(df_merged, df_compradores):
    """LEFT JOIN con tabla de compradores por nombre corto del curso."""
    if df_compradores.empty:
        df_merged["comprador_nombre"] = ""
        df_merged["empresa"] = ""
        df_merged["email_comprador"] = ""
        logger.info("Compradores vacío — columnas con valores por defecto")
        return df_merged

    resultado = df_merged.merge(
        df_compradores,
        left_on="nombre_corto",
        right_on="id_curso_moodle",
        how="left",
        suffixes=("", "_comp"),
    )

    resultado["comprador_nombre"] = resultado["comprador_nombre"].fillna("")
    resultado["empresa"] = resultado["empresa"].fillna("")
    resultado["email_comprador"] = resultado["email_comprador"].fillna("")

    # Quitar columna auxiliar
    if "id_curso_moodle" in resultado.columns:
        resultado = resultado.drop(columns=["id_curso_moodle"])

    logger.info(
        "Merge compradores: %d filas, %d con comprador asignado",
        len(resultado),
        (resultado["comprador_nombre"].str.strip() != "").sum(),
    )
    return resultado
