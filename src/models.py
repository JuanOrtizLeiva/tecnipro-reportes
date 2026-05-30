"""Modelos SQLAlchemy para tecnipro_reportes."""

from datetime import date, datetime

from sqlalchemy import (
    Column, Integer, String, Text, Float, SmallInteger, Date,
    DateTime, ForeignKey, UniqueConstraint, Index, func,
)
from sqlalchemy.orm import relationship

from .database import Base


class Curso(Base):
    __tablename__ = "cursos"

    id = Column(Integer, primary_key=True)
    id_moodle = Column(Text, nullable=False, unique=True)
    id_sence = Column(Text, default="")
    nombre = Column(Text, nullable=False, default="")
    nombre_corto = Column(Text, nullable=False, default="")
    categoria = Column(Text, default="")
    modalidad = Column(Text, default="")
    fecha_inicio = Column(Date)
    fecha_fin = Column(Date)
    fecha_inicio_sence = Column(Text, default="")
    fecha_termino_sence = Column(Text, default="")
    estado_dj_otec = Column(Text, default="")
    estado_curso_sence = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    inscripciones = relationship("Inscripcion", back_populates="curso", cascade="all, delete-orphan")
    comprador = relationship("Comprador", back_populates="curso", uselist=False, cascade="all, delete-orphan")
    snapshots = relationship("SnapshotDiario", back_populates="curso", cascade="all, delete-orphan")


class Estudiante(Base):
    __tablename__ = "estudiantes"

    id = Column(Integer, primary_key=True)
    rut = Column(Text, nullable=False, unique=True)
    nombre = Column(Text, nullable=False, default="")
    email = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    inscripciones = relationship("Inscripcion", back_populates="estudiante", cascade="all, delete-orphan")


class Inscripcion(Base):
    __tablename__ = "inscripciones"

    id = Column(Integer, primary_key=True)
    curso_id = Column(Integer, ForeignKey("cursos.id", ondelete="CASCADE"), nullable=False)
    estudiante_id = Column(Integer, ForeignKey("estudiantes.id", ondelete="CASCADE"), nullable=False)
    progreso = Column(Float)
    calificacion = Column(Float)
    evaluaciones_rendidas = Column(SmallInteger, default=0)
    total_evaluaciones = Column(SmallInteger, default=0)
    promedio_evaluadas = Column(Float)
    ultimo_acceso = Column(DateTime(timezone=True))
    dias_sin_ingreso = Column(Integer)
    estado = Column(String(1), default="P")
    riesgo = Column(Text)
    id_sence = Column(Text, default="")
    sence_n_ingresos = Column(Integer, default=0)
    sence_estado = Column(Text, default="NO_APLICA")
    sence_dj = Column(Text, default="")
    estado_curso = Column(Text, default="active")
    dias_para_termino = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("curso_id", "estudiante_id", name="uq_inscripcion_curso_est"),
    )

    curso = relationship("Curso", back_populates="inscripciones")
    estudiante = relationship("Estudiante", back_populates="inscripciones")
    snapshots = relationship("SnapshotEstudiante", back_populates="inscripcion", cascade="all, delete-orphan")


class Comprador(Base):
    __tablename__ = "compradores"

    id = Column(Integer, primary_key=True)
    curso_id = Column(Integer, ForeignKey("cursos.id", ondelete="CASCADE"), nullable=False, unique=True)
    nombre = Column(Text, nullable=False, default="")
    empresa = Column(Text, default="")
    email = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    curso = relationship("Curso", back_populates="comprador")


class SnapshotDiario(Base):
    __tablename__ = "snapshots_diarios"

    id = Column(Integer, primary_key=True)
    fecha = Column(Date, nullable=False)
    curso_id = Column(Integer, ForeignKey("cursos.id", ondelete="CASCADE"), nullable=False)
    id_moodle = Column(Text, nullable=False)
    total_estudiantes = Column(Integer, default=0)
    promedio_progreso = Column(Float, default=0.0)
    promedio_calificacion = Column(Float, default=0.0)
    aprobados = Column(Integer, default=0)
    reprobados = Column(Integer, default=0)
    en_proceso = Column(Integer, default=0)
    riesgo_alto = Column(Integer, default=0)
    riesgo_medio = Column(Integer, default=0)
    riesgo_bajo = Column(Integer, default=0)
    conectados_sence = Column(Integer, default=0)
    avance_temporal = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("fecha", "curso_id", name="uq_snapshot_fecha_curso"),
    )

    curso = relationship("Curso", back_populates="snapshots")


class SnapshotEstudiante(Base):
    __tablename__ = "snapshots_estudiantes"

    id = Column(Integer, primary_key=True)
    fecha = Column(Date, nullable=False)
    inscripcion_id = Column(Integer, ForeignKey("inscripciones.id", ondelete="CASCADE"), nullable=False)
    progreso = Column(Float)
    calificacion = Column(Float)
    estado = Column(String(1))
    riesgo = Column(Text)
    sence_n_ingresos = Column(Integer, default=0)
    dias_sin_ingreso = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("fecha", "inscripcion_id", name="uq_snap_est_fecha_insc"),
    )

    inscripcion = relationship("Inscripcion", back_populates="snapshots")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    status = Column(Text, default="running")
    total_cursos = Column(Integer)
    total_estudiantes = Column(Integer)
    error_message = Column(Text)
    triggered_by = Column(Text, default="timer")


class FeriadoChile(Base):
    """Feriados oficiales de Chile por año. Se carga anualmente."""
    __tablename__ = "feriados_chile"

    id = Column(Integer, primary_key=True)
    fecha = Column(Date, nullable=False)
    nombre = Column(Text, nullable=False)
    anio = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("fecha", name="uq_feriado_fecha"),
        Index("ix_feriado_anio", "anio"),
    )


class LogEnvioAvance(Base):
    """Log de cada correo de avance semanal enviado a alumnos."""
    __tablename__ = "log_envio_avance"

    id = Column(Integer, primary_key=True)
    fecha_envio = Column(DateTime(timezone=True), server_default=func.now())
    estudiante_id = Column(Integer, ForeignKey("estudiantes.id"), nullable=True)
    estudiante_nombre = Column(Text, nullable=False)
    estudiante_email = Column(Text, nullable=False)
    curso_id = Column(Integer, ForeignKey("cursos.id", ondelete="SET NULL"), nullable=True)
    curso_nombre = Column(Text, nullable=False)
    curso_id_moodle = Column(Text)
    progreso = Column(Float)
    avance_temporal = Column(Integer)
    estado = Column(String(10), nullable=False)  # OK, ERROR
    error_detalle = Column(Text)
    remitente = Column(Text, default="ygonzalez@duocapital.cl")
    asunto = Column(Text)
    cuerpo_html = Column(Text)

    __table_args__ = (
        Index("ix_log_envio_fecha", "fecha_envio"),
        Index("ix_log_envio_estado", "estado"),
    )


class SeguimientoDjSence(Base):
    """Seguimiento de firma de DJ por acción SENCE (IDSence).

    Una fila por IDSence terminado bajo seguimiento. Permite enviar a la
    coordinadora un correo diario con las DJ pendientes hasta llegar a 0, y un
    correo de cierre al completarse, sin duplicar ni reabrir cursos ya cerrados.
    El seguimiento es por IDSence (no por curso): un curso Moodle puede tener
    más de un código SENCE.
    """
    __tablename__ = "seguimiento_dj_sence"

    id = Column(Integer, primary_key=True)
    id_sence = Column(Text, nullable=False, unique=True)
    curso_id = Column(Integer, ForeignKey("cursos.id", ondelete="SET NULL"), nullable=True)
    curso_nombre = Column(Text, default="")
    fecha_termino = Column(Date)
    estado = Column(Text, default="activo")  # activo | cerrado
    n_correos = Column(Integer, default=0)
    ultimo_pendientes = Column(Integer)
    fecha_primer_correo = Column(DateTime(timezone=True))
    fecha_ultimo_correo = Column(DateTime(timezone=True))
    fecha_cierre = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("id_sence", name="uq_seg_dj_sence"),
        Index("ix_seg_dj_estado", "estado"),
    )
