-- Audit sheets: the versioned structure-review exchange for Book Forge.
--
-- The system generates a sheet proposing the unit -> chapter breakdown, the SME
-- fills it in and uploads it back, and BOTH directions are kept as immutable
-- rows so any earlier version can be retrieved.
--
-- `version` is one monotonic sequence per project spanning both directions, so
-- the rows read as a single ordered conversation:
--     v1 generated -> v2 submitted -> v3 generated -> v4 submitted ...
--
-- Dev environments pick this up automatically via Base.metadata.create_all();
-- this script exists so production can be migrated explicitly.

CREATE TABLE IF NOT EXISTS book_forge_audit_sheets (
    id                BIGINT       NOT NULL AUTO_INCREMENT,
    project_id        BIGINT       NOT NULL,
    version           INT          NOT NULL DEFAULT 1,

    -- 'generated' = produced by the system for review.
    -- 'submitted'  = uploaded back by the end user / SME.
    sheet_type        VARCHAR(20)  NOT NULL,
    -- For a 'submitted' row: the 'generated' version it answers.
    source_version    INT          NULL,

    stored_filename   VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NULL,
    file_path         TEXT         NOT NULL,
    file_size         BIGINT       NULL,
    checksum_sha256   VARCHAR(64)  NULL,

    -- Sheet content as structured data, so downstream generation never has to
    -- re-open the workbook.
    payload_json      JSON         NULL,

    row_count         INT          NULL,
    weighted_count    INT          NULL,

    -- 'current' for the newest row of its sheet_type, else 'superseded'.
    status            VARCHAR(30)  NOT NULL DEFAULT 'current',
    notes             TEXT         NULL,

    created_by        BIGINT       NULL,
    created_at        TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP    NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
    is_deleted        TINYINT(1)   NOT NULL DEFAULT 0,

    PRIMARY KEY (id),
    -- One row per (project, version): the version sequence must stay unique
    -- even if two generations race.
    UNIQUE KEY uq_audit_sheet_project_version (project_id, version),
    KEY ix_audit_sheet_project (project_id),
    KEY ix_audit_sheet_type (sheet_type),
    KEY ix_audit_sheet_status (status),
    -- Serves the common "latest sheet of this kind" lookup.
    KEY ix_audit_sheet_project_type_version (project_id, sheet_type, version),

    CONSTRAINT fk_audit_sheet_project
        FOREIGN KEY (project_id) REFERENCES book_forge_projects (id)
        ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
