-- Tabla de seguimiento de firma de DJ por acción SENCE (IDSence).
-- Una fila por IDSence terminado bajo seguimiento: permite enviar a la
-- coordinadora un correo diario con las DJ pendientes hasta llegar a 0, y un
-- correo de cierre al completarse, sin duplicar ni reabrir cursos cerrados.
-- Idempotente (CREATE ... IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS seguimiento_dj_sence (
    id                  SERIAL PRIMARY KEY,
    id_sence            TEXT NOT NULL,
    curso_id            INTEGER REFERENCES cursos(id) ON DELETE SET NULL,
    curso_nombre        TEXT DEFAULT '',
    fecha_termino       DATE,
    estado              TEXT DEFAULT 'activo',          -- activo | cerrado
    n_correos           INTEGER DEFAULT 0,
    ultimo_pendientes   INTEGER,
    fecha_primer_correo TIMESTAMPTZ,
    fecha_ultimo_correo TIMESTAMPTZ,
    fecha_cierre        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_seg_dj_sence UNIQUE (id_sence)
);

CREATE INDEX IF NOT EXISTS ix_seg_dj_estado ON seguimiento_dj_sence (estado);

COMMIT;
