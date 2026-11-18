-- ---------------------------------------------------------------------------
-- book_forge_project_status : master list of workflow statuses a project moves
-- through (draft -> sources_added -> building_knowledge -> knowledge_ready ->
-- generating_blueprint -> blueprint_ready, plus failed).
--
-- status_name holds the internal enum value (lower_snake_case, unique); the UI
-- label and the "when" description live alongside it so the front end can render
-- a friendly name without hard-coding it.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS book_forge_project_status (
    status_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    status_name        VARCHAR(50)  NOT NULL UNIQUE,      -- internal enum, e.g. 'draft'
    status_label       VARCHAR(100) NOT NULL,             -- UI label,       e.g. 'Draft'
    status_description VARCHAR(255) NULL,                 -- when this status applies
    sort_order         INT          NOT NULL DEFAULT 0,   -- display / progression order
    created_by         BIGINT       NULL,
    updated_by         BIGINT       NULL,
    created_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed the workflow statuses. Idempotent: re-running keeps labels/descriptions
-- in sync without creating duplicates (status_name is UNIQUE).
INSERT INTO book_forge_project_status
    (status_name, status_label, status_description, sort_order)
VALUES
    ('draft',                'Draft',                   'Project created, no sources yet',                     1),
    ('sources_added',        'Sources Added',           'At least one source uploaded (any type)',             2),
    ('building_knowledge',   'Building Knowledge Base', 'Ingestion running (parse -> chunk -> embed -> store)', 3),
    ('knowledge_ready',      'Knowledge Base Ready',    'Vectors stored, ready to generate',                   4),
    ('generating_blueprint', 'Generating Blueprint',    'LLM generation running',                              5),
    ('blueprint_ready',      'Blueprint Ready',         'Blueprint generated & saved',                         6),
    ('failed',               'Failed',                  'Any step errored',                                    99)
ON DUPLICATE KEY UPDATE
    status_label       = VALUES(status_label),
    status_description = VALUES(status_description),
    sort_order         = VALUES(sort_order);
