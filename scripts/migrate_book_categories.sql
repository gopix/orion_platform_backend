-- ============================================================================
-- Book category master + id-based FK from projects.
-- Run once, in order. Take a DB backup first.
--
-- If you are starting FRESH (recreating book_forge_projects with a category_id
-- column already), you only need step 1 (the category table) and can skip the
-- backfill/ALTER steps.
-- ============================================================================

-- 1) Master category table: book_forge_category (id, category_name).
CREATE TABLE IF NOT EXISTS book_forge_category (
    id                   BIGINT       NOT NULL AUTO_INCREMENT,
    category_name        VARCHAR(100) NOT NULL,
    category_description VARCHAR(500) NULL,
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_bfc_name (category_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---- The steps below migrate an EXISTING projects table that still has the old
-- ---- string `category` column. Skip them if you recreated the table fresh.

-- 2) Normalize existing project.category strings to the canonical name form.
UPDATE book_forge_projects
SET category = LOWER(REPLACE(REPLACE(TRIM(category), ' ', '_'), '-', '_'))
WHERE category IS NOT NULL AND TRIM(category) <> '';

-- 3) Backfill categories from existing project categories and from prompts.
INSERT IGNORE INTO book_forge_category (category_name)
SELECT DISTINCT category FROM book_forge_projects
WHERE category IS NOT NULL AND TRIM(category) <> '';

-- (category derived from the template name suffix; 22 = len('blueprint_generation_')+1)
INSERT IGNORE INTO book_forge_category (category_name)
SELECT DISTINCT SUBSTRING(t.name, 22) FROM book_forge_prompt_templates t
WHERE t.name LIKE 'blueprint_generation\_%' ESCAPE '\\';

-- 4) Add the new category_id column.
ALTER TABLE book_forge_projects ADD COLUMN category_id BIGINT NULL AFTER book_title;

-- 5) Backfill category_id from the old string category.
UPDATE book_forge_projects p
JOIN book_forge_category c ON c.category_name = p.category
SET p.category_id = c.id;

-- 6) Add the hard foreign key.
ALTER TABLE book_forge_projects
    ADD CONSTRAINT fk_project_category
    FOREIGN KEY (category_id) REFERENCES book_forge_category (id);

-- 7) Drop the old string column (only after verifying the backfill in step 5).
ALTER TABLE book_forge_projects DROP COLUMN category;

-- 8) (Optional) verify.
-- SELECT * FROM book_forge_category ORDER BY category_name;
-- SELECT id, category_id FROM book_forge_projects WHERE category_id IS NOT NULL;
