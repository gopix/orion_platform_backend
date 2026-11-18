-- ==========================================
-- ORION PLATFORM DATABASE SCHEMA (corrected)
--   * de-duplicated book_forge_prompt_* tables (were defined 2-3x)
--   * book_forge_category created BEFORE tables that FK to it
--   * book_forge_prompt_templates keeps description + active_version
--     (required by the Prompt Engine) AND category_id (FK to category)
-- ==========================================

CREATE DATABASE IF NOT EXISTS orion_db;
USE orion_db;

-- ==========================================
-- ORGANIZATIONS / ROLES / USERS
-- ==========================================
CREATE TABLE organizations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    organization_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT NULL,
    updated_by INT NULL
);

CREATE TABLE roles (
    role_id INT AUTO_INCREMENT PRIMARY KEY,
    role_name VARCHAR(255) NOT NULL,
    role_description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO roles(role_name, role_description, is_active) VALUES
('USER', 'normal user', 1),
('ADMIN', 'administrator', 1),
('BookForge_SME', 'book forge SME', 1),
('BookForge_EDITOR', 'book forge editor', 1);

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    organization_id INT,
    role_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT NULL,
    updated_by INT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (role_id) REFERENCES roles(role_id)
);

-- ==========================================
-- PUBLISHING / EDITOR / SALES (unchanged)
-- ==========================================
CREATE TABLE manuscripts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    title VARCHAR(500),
    author VARCHAR(255),
    status VARCHAR(50) DEFAULT 'Submitted',
    file_path VARCHAR(512),
    file_name VARCHAR(255),
    file_size INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT NULL,
    updated_by INT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE editor_analysis_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    manuscript_id INT NOT NULL,
    analysis_json JSON,
    model_version VARCHAR(50),
    processing_time_seconds DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT NULL,
    updated_by INT NULL,
    FOREIGN KEY (manuscript_id) REFERENCES manuscripts(id)
);

CREATE TABLE ai_agent_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    manuscript_id INT,
    agent_name VARCHAR(100),
    input_text TEXT,
    output_text TEXT,
    latency_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (manuscript_id) REFERENCES manuscripts(id)
);

CREATE TABLE books (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255),
    subject VARCHAR(100),
    isbn VARCHAR(50),
    price DECIMAL(10,2),
    organization_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE inventory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    book_id INT,
    warehouse VARCHAR(100),
    quantity INT,
    organization_id INT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id)
);

CREATE TABLE distributors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255),
    city VARCHAR(100),
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sales (
    id INT AUTO_INCREMENT PRIMARY KEY,
    book_id INT,
    distributor_id INT,
    quantity INT,
    total_amount DECIMAL(10,2),
    sale_date DATE,
    organization_id INT,
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (distributor_id) REFERENCES distributors(id)
);

CREATE TABLE returns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    book_id INT,
    distributor_id INT,
    quantity INT,
    return_date DATE,
    organization_id INT,
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (distributor_id) REFERENCES distributors(id)
);

CREATE TABLE payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    distributor_id INT,
    amount DECIMAL(10,2),
    payment_date DATE,
    organization_id INT,
    FOREIGN KEY (distributor_id) REFERENCES distributors(id)
);

CREATE TABLE book_structure_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    book_id INT NULL,
    template_name VARCHAR(255),
    structure_json JSON,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (book_id) REFERENCES books(id)
);

-- ==========================================
-- ACCESSIBILITY
-- ==========================================
CREATE TABLE master_accessibility_check (
    check_id INT AUTO_INCREMENT PRIMARY KEY,
    check_code VARCHAR(100) NOT NULL UNIQUE,
    check_name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(50) NOT NULL,
    default_priority VARCHAR(10) NOT NULL,
    wcag_reference VARCHAR(50),
    pdfua_reference VARCHAR(50),
    remediation_guidance TEXT,
    agent_code VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (default_priority IN ('HIGH', 'MEDIUM', 'LOW'))
);

CREATE TABLE org_project_accessibility_check (
    id INT AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    project_id VARCHAR(100) NULL,
    master_check_id INT NOT NULL,
    check_code VARCHAR(100) NOT NULL,
    check_name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(50) NOT NULL,
    default_priority VARCHAR(10) NOT NULL,
    wcag_reference VARCHAR(50),
    pdfua_reference VARCHAR(50),
    remediation_guidance TEXT,
    agent_code VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_org_project_check_code (organization_id, project_id, check_code),
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (master_check_id) REFERENCES master_accessibility_check(check_id),
    CHECK (default_priority IN ('HIGH', 'MEDIUM', 'LOW'))
);

CREATE TABLE accessibility_mis (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    file_executed VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- ==========================================
-- BOOK FORGE
--   NOTE: category is created first (projects + prompt_templates FK to it).
-- ==========================================
CREATE TABLE book_forge_category (
    id                   BIGINT AUTO_INCREMENT PRIMARY KEY,
    category_name        VARCHAR(100) NOT NULL UNIQUE,
    category_description VARCHAR(500) NULL,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Workflow status master. Created + seeded BEFORE book_forge_projects, which
-- FKs book_status -> status_name (and defaults to 'draft', so that row must exist).
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

CREATE TABLE book_forge_projects (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    book_title              VARCHAR(255) NOT NULL,
    category_id             BIGINT,
    book_subject            VARCHAR(255),
    target_audience         VARCHAR(255),
    language_code           VARCHAR(10),
    expected_pages          INT,
    chapter_count           INT,
    publisher_name          VARCHAR(255),
    edition                 VARCHAR(50),
    primary_output_format   VARCHAR(50),
    book_description        TEXT,
    submission_deadline     DATE,
    book_status             VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_by              BIGINT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_deleted              BOOLEAN DEFAULT FALSE,
    KEY ix_bfp_category (category_id),
    KEY ix_bfp_status (book_status),
    CONSTRAINT fk_project_category FOREIGN KEY (category_id)
        REFERENCES book_forge_category (id),
    CONSTRAINT fk_project_status FOREIGN KEY (book_status)
        REFERENCES book_forge_project_status (status_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE book_forge_documents (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id        BIGINT NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename   VARCHAR(255) NOT NULL,
    file_path         VARCHAR(512) NOT NULL,
    file_extension    VARCHAR(20),
    mime_type         VARCHAR(150),
    file_size         BIGINT,
    document_type     VARCHAR(50),
    created_by        BIGINT NOT NULL,
    created_at        TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_deleted        BOOLEAN NOT NULL DEFAULT FALSE,
    INDEX idx_project_id (project_id),
    FOREIGN KEY (project_id) REFERENCES book_forge_projects (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE book_forge_document_processing (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id          BIGINT NOT NULL,
    document_id         BIGINT NOT NULL,
    processing_stage    VARCHAR(50) NOT NULL,
    processing_status   VARCHAR(30) DEFAULT 'PENDING',
    started_at          DATETIME,
    completed_at        DATETIME,
    error_message       TEXT,
    processing_version  VARCHAR(30),
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES book_forge_documents(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Prompt Engine: templates carry description + active_version (used by the code)
-- and an optional category_id FK to the category master.
CREATE TABLE book_forge_prompt_templates (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(255) NOT NULL UNIQUE,
    category_id    BIGINT NULL,
    description    TEXT,
    active_version INT,
    status         VARCHAR(30) NOT NULL DEFAULT 'draft',
    created_by     BIGINT,
    created_at     TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_pt_category (category_id),
    CONSTRAINT fk_pt_category FOREIGN KEY (category_id) REFERENCES book_forge_category(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE book_forge_prompt_versions (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    template_id   BIGINT NOT NULL,
    version       INT NOT NULL,
    template_text TEXT NOT NULL,
    model         VARCHAR(100),
    temperature   FLOAT,
    max_tokens    INT,
    status        VARCHAR(30) NOT NULL DEFAULT 'draft',
    created_by    BIGINT,
    created_at    TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_pv_template (template_id),
    CONSTRAINT fk_pv_template FOREIGN KEY (template_id) REFERENCES book_forge_prompt_templates(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE book_forge_prompt_variables (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    template_id   BIGINT NOT NULL,
    name          VARCHAR(100) NOT NULL,
    type          VARCHAR(30) NOT NULL DEFAULT 'string',
    required      TINYINT(1) NOT NULL DEFAULT 1,
    default_value TEXT,
    description   TEXT,
    KEY ix_pvar_template (template_id),
    CONSTRAINT fk_pvar_template FOREIGN KEY (template_id) REFERENCES book_forge_prompt_templates(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE book_forge_prompt_executions (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id      VARCHAR(64),
    prompt_id       BIGINT,
    version         INT,
    provider        VARCHAR(50),
    model           VARCHAR(100),
    rendered_prompt TEXT,
    response        TEXT,
    input_tokens    INT,
    output_tokens   INT,
    latency_ms      FLOAT,
    cost            FLOAT,
    status          VARCHAR(30),
    created_at      TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_pe_request (request_id),
    KEY ix_pe_prompt (prompt_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE book_forge_blueprints (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    project_id     BIGINT       NOT NULL,
    version        INT          NOT NULL DEFAULT 1,
    title          VARCHAR(255) NULL,
    description    TEXT         NULL,
    blueprint_json JSON         NOT NULL,
    status         VARCHAR(30)  NOT NULL DEFAULT 'generated',
    created_by     BIGINT       NULL,
    created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_deleted     TINYINT(1)   NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY ix_bfb_project_id (project_id),
    KEY ix_bfb_status (status),
    UNIQUE KEY uq_bfb_project_version (project_id, version),
    CONSTRAINT fk_bfb_project FOREIGN KEY (project_id) REFERENCES book_forge_projects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ==========================================
-- SAMPLE DATA
-- ==========================================
INSERT INTO organizations(organization_name) VALUES ('Orion'), ('Elsevier'), ('Wiley');

INSERT INTO users(user_name, email, password_hash, organization_id, role_id)
VALUES ('Test User', 'test@gmail.com', '12345678', 1, 1);

INSERT INTO books (title, subject, isbn, price) VALUES
('Math Class 10', 'Math', 'ISBN001', 250),
('Science Class 10', 'Science', 'ISBN002', 300),
('Hindi Vyakaran', 'Hindi', 'ISBN003', 200);

INSERT INTO distributors (name, city, phone) VALUES
('Rama Book Depot', 'Meerut', '9876543210'),
('Goyal Bros', 'Meerut', '9123456780'),
('Patna Distributors', 'Patna', '9988776655');


CREATE TABLE web_accessibility_websites (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    base_url VARCHAR(2048) NOT NULL,
    description VARCHAR(1000),
    accessibility_status VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
    environment VARCHAR(50) NOT NULL DEFAULT 'PRODUCTION',
    crawl_enabled TINYINT(1) NOT NULL DEFAULT 0,
    crawl_frequency VARCHAR(50),
    authentication_required TINYINT(1) NOT NULL DEFAULT 0,
    authentication_type VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_scan_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (id),
    INDEX idx_web_accessibility_websites_status (accessibility_status),
    INDEX idx_web_accessibility_websites_environment (environment)
);

-- Pages discovered for each website. Must exist before scan foreign keys are added.
CREATE TABLE web_accessibility_pages (
    id BIGINT NOT NULL AUTO_INCREMENT,
    website_id BIGINT NOT NULL,
    url VARCHAR(2048) NOT NULL,
    url_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_web_accessibility_pages_website_url_hash (website_id, url_hash),
    KEY ix_web_accessibility_pages_id (id),
    CONSTRAINT fk_web_accessibility_pages_website
        FOREIGN KEY (website_id) REFERENCES web_accessibility_websites (id)
);

-- Crawl runs for each website. Created before scans so scan.crawl_id can reference it.
CREATE TABLE web_accessibility_crawls (
    id BIGINT NOT NULL AUTO_INCREMENT,
    website_id BIGINT NOT NULL,
    discovery_source VARCHAR(20) DEFAULT NULL,
    max_pages INT DEFAULT NULL,
    pages_discovered INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_web_accessibility_crawls_website_id (website_id),
    KEY ix_web_accessibility_crawls_id (id),
    CONSTRAINT fk_web_accessibility_crawls_website
        FOREIGN KEY (website_id) REFERENCES web_accessibility_websites (id)
);

CREATE TABLE web_accessibility_scans (
    id BIGINT NOT NULL AUTO_INCREMENT,
    website_id BIGINT NOT NULL,
    url VARCHAR(2048) NOT NULL,
    title VARCHAR(500),
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    http_status INT,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    total_issues INT NOT NULL DEFAULT 0,
    accessibility_score DECIMAL(5,2),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    crawl_frequency VARCHAR(50),
    authentication_required TINYINT(1) NOT NULL DEFAULT 0,
    authentication_type VARCHAR(50),
    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    page_id BIGINT NULL,
    crawl_id BIGINT NULL,
    PRIMARY KEY (id),
    INDEX idx_web_accessibility_scans_website (website_id),
    INDEX idx_web_accessibility_scans_status (status),
    INDEX idx_web_accessibility_scans_url (url(255)),
    INDEX idx_web_accessibility_scans_page_id (page_id),
    INDEX idx_web_accessibility_scans_crawl_id (crawl_id),
    CONSTRAINT fk_web_accessibility_scans_website
        FOREIGN KEY (website_id) REFERENCES web_accessibility_websites (id),
    CONSTRAINT fk_web_accessibility_scans_page_id
        FOREIGN KEY (page_id) REFERENCES web_accessibility_pages (id),
    CONSTRAINT fk_web_accessibility_scans_crawl_id
        FOREIGN KEY (crawl_id) REFERENCES web_accessibility_crawls (id)
);
CREATE TABLE web_accessibility_rules (
    id BIGINT NOT NULL AUTO_INCREMENT,
    rule_code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    wcag_criterion VARCHAR(20) NOT NULL,
    wcag_level VARCHAR(10) NOT NULL,
    category VARCHAR(100),
    severity VARCHAR(50),
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE INDEX uk_web_accessibility_rules_code (rule_code)
);

CREATE TABLE web_accessibility_issues (
    id BIGINT NOT NULL AUTO_INCREMENT,
    scan_id BIGINT NOT NULL,
    page_id BIGINT NOT NULL,
    rule_id BIGINT NOT NULL,
    severity VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'OPEN',
    element_selector VARCHAR(2000),
    html_snippet TEXT,
    message VARCHAR(2000),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_web_accessibility_issues_scan (scan_id),
    INDEX idx_web_accessibility_issues_page (page_id),
    INDEX idx_web_accessibility_issues_rule (rule_id),
    INDEX idx_web_accessibility_issues_status (status)
);


INSERT INTO web_accessibility_rules
    (rule_code, name, wcag_criterion, wcag_level, category, severity)
VALUES
-- Images
('IMG-001', 'Images must have alternative text',
 '1.1.1', 'A', 'IMAGES', 'CRITICAL'),
('IMG-002', 'Decorative images must be marked as decorative',
 '1.1.1', 'A', 'IMAGES', 'SERIOUS'),
('IMG-003', 'Image links must have an accessible name',
 '1.1.1', 'A', 'IMAGES', 'SERIOUS'),
-- Page Structure / Headings
('HDR-001', 'Page must have a descriptive title',
 '2.4.2', 'A', 'HEADINGS', 'SERIOUS'),
('HDR-002', 'Headings must follow a logical hierarchy',
 '1.3.1', 'A', 'HEADINGS', 'SERIOUS'),
('HDR-003', 'Heading elements must contain meaningful text',
 '1.3.1', 'A', 'HEADINGS', 'SERIOUS'),
-- Language
('LANG-001', 'Page must have a valid language declaration',
 '3.1.1', 'A', 'LANGUAGE', 'SERIOUS'),
-- Links
('LINK-001', 'Links must have an accessible name',
 '2.4.4', 'A', 'LINKS', 'SERIOUS'),
('LINK-002', 'Links must have meaningful link text',
 '2.4.4', 'A', 'LINKS', 'SERIOUS'),
-- Forms
('FORM-001', 'Form controls must have accessible labels',
 '1.3.1', 'A', 'FORMS', 'CRITICAL'),
('FORM-002', 'Form inputs must have an accessible name',
 '4.1.2', 'A', 'FORMS', 'CRITICAL'),
('FORM-003', 'Required form fields must be programmatically identified',
 '3.3.2', 'A', 'FORMS', 'SERIOUS'),
('FORM-004', 'Form errors must be identified and described',
 '3.3.1', 'A', 'FORMS', 'SERIOUS');
-- Ph-2

INSERT INTO web_accessibility_rules
    (rule_code, name, wcag_criterion, wcag_level, category, severity)
VALUES
-- Landmarks / Structure
('LAND-001', 'Page must have a main landmark',
 '1.3.1', 'A', 'LANDMARKS', 'SERIOUS'),
('LAND-002', 'Landmarks must have unique accessible names where required',
 '2.4.1', 'A', 'LANDMARKS', 'MODERATE'),
-- Tables
('TABLE-001', 'Data tables must identify header cells',
 '1.3.1', 'A', 'TABLES', 'SERIOUS'),
('TABLE-002', 'Tables must have an accessible caption or name where appropriate',
 '1.3.1', 'A', 'TABLES', 'MODERATE'),
-- ARIA / Semantics
('ARIA-001', 'ARIA roles must be valid',
 '4.1.2', 'A', 'ARIA', 'SERIOUS'),
('ARIA-002', 'ARIA attributes must be valid for the assigned role',
 '4.1.2', 'A', 'ARIA', 'SERIOUS');

-- Phase-3 
INSERT INTO web_accessibility_rules
    (rule_code, name, wcag_criterion, wcag_level, category, severity)
VALUES
-- Color / Contrast
('COLOR-001', 'Normal text must meet minimum contrast ratio',
 '1.4.3', 'AA', 'COLOR', 'CRITICAL'),
('COLOR-002', 'Large text must meet minimum contrast ratio',
 '1.4.3', 'AA', 'COLOR', 'SERIOUS'),
('COLOR-003', 'User interface components must have sufficient contrast',
 '1.4.11', 'AA', 'COLOR', 'SERIOUS'),
-- Keyboard
('KEY-001', 'Interactive elements must be keyboard accessible',
 '2.1.1', 'A', 'KEYBOARD', 'CRITICAL'),
('KEY-002', 'Keyboard focus must be visible',
 '2.4.7', 'AA', 'KEYBOARD', 'SERIOUS'),
('KEY-003', 'Page must not contain a keyboard trap',
 '2.1.2', 'A', 'KEYBOARD', 'CRITICAL'),
-- Bypass
('BYPASS-001', 'Page must provide a mechanism to bypass repeated content',
 '2.4.1', 'A', 'NAVIGATION', 'SERIOUS');


ALTER TABLE web_accessibility_issues ADD COLUMN updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE web_accessibility_rules ADD COLUMN updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE web_accessibility_issues ADD COLUMN times_seen INTEGER NOT NULL DEFAULT 1;
ALTER TABLE web_accessibility_issues ADD COLUMN last_seen_scan_id BIGINT;
ALTER TABLE web_accessibility_issues ADD COLUMN resolved_at TIMESTAMP NULL;
ALTER TABLE web_accessibility_issues ADD COLUMN resolved_in_scan_id BIGINT;



CREATE TABLE customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  customer_address VARCHAR(500),
  phone_no VARCHAR(20),
  email_id VARCHAR(255) UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX ix_customers_customer_name (customer_name)
);

CREATE TABLE ce_projects (
  project_id INT AUTO_INCREMENT PRIMARY KEY,
  project_name VARCHAR(255) NOT NULL,
  customer_id INT NOT NULL,
  project_description TEXT,
  project_manager VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by INT,
  INDEX ix_ce_projects_project_name (project_name),
  INDEX ix_ce_projects_customer_id (customer_id),
  CONSTRAINT fk_ce_projects_customer FOREIGN KEY (customer_id)
    REFERENCES customers(id) ON DELETE RESTRICT
);

CREATE TABLE ce_template (
  template_id INT AUTO_INCREMENT PRIMARY KEY,
  template_name VARCHAR(255) NOT NULL,
  project_id INT NOT NULL,
  template_design LONGTEXT,
  template_description TEXT,
  template_status VARCHAR(20) NOT NULL DEFAULT 'draft',
  INDEX ix_ce_template_template_name (template_name),
  INDEX ix_ce_template_project_id (project_id),
  INDEX ix_ce_template_template_status (template_status),
  CONSTRAINT fk_ce_template_project FOREIGN KEY (project_id)
    REFERENCES ce_projects(project_id) ON DELETE RESTRICT
);

CREATE TABLE feature_groups (
  feature_group_id INT AUTO_INCREMENT PRIMARY KEY,
  group_name VARCHAR(255) NOT NULL,
  group_code INT NOT NULL UNIQUE,
  group_description TEXT,
  created_by INT, updated_by INT,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE main_features (
  feature_id INT AUTO_INCREMENT PRIMARY KEY,
  feature_name VARCHAR(255) NOT NULL,
  feature_code INT NOT NULL UNIQUE,
  group_code INT NULL,
  feature_description TEXT,
  created_by INT, updated_by INT,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY (group_code),
  FOREIGN KEY (group_code) REFERENCES feature_groups(group_code) ON DELETE CASCADE
);

CREATE TABLE template_features (
  id INT AUTO_INCREMENT PRIMARY KEY,
  template_id INT NOT NULL,
  feature_id INT NOT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  UNIQUE KEY uq_template_feature (template_id, feature_id),
  KEY (feature_id),
  FOREIGN KEY (template_id) REFERENCES ce_template(template_id) ON DELETE CASCADE,
  FOREIGN KEY (feature_id) REFERENCES main_features(feature_id) ON DELETE CASCADE
);


INSERT INTO feature_groups
  (feature_group_id, group_name, group_code, group_description, created_by, updated_by, created_at, updated_at)
VALUES
  (1,  'CLEAN_UP',              1000,  'cleaning up the manuscript',            0, 0, NOW(), NOW()),
  (2,  'PUNCTUATION',           2000,  'Punctuation And Formatting',            0, 0, NOW(), NOW()),
  (3,  'LIST',                  3000,  'List',                                  0, 0, NOW(), NOW()),
  (4,  'ACRONYMS_ABBREVIATION', 4000,  'Acronyms And Abbreviation',             0, 0, NOW(), NOW()),
  (5,  'HEADINGS',              5000,  'Headings handling',                     0, 0, NOW(), NOW()),
  (6,  'NUMBERS',               6000,  'Number handling',                       0, 0, NOW(), NOW()),
  (7,  'DATES_TIME',            7000,  'Dates and time',                        0, 0, NOW(), NOW()),
  (8,  'CAPITALIZATION',        8000,  'Capitalization',                        0, 0, NOW(), NOW()),
  (9,  'GRAMMAR_READABILITY',   9000,  'Grammar And Readability',               0, 0, NOW(), NOW()),
  (10, 'QUOTATIONS',            10000, 'QUOTATIONS',                            0, 0, NOW(), NOW()),
  (11, 'GENERAL',               0,     '',                                      0, 0, NOW(), NOW()),
  (12, 'ART',                   11000, 'FIGURES, TABLES, PLATES, PHOTOS, ETC.', 0, 0, NOW(), NOW());

ALTER TABLE feature_groups AUTO_INCREMENT = 13;

SET NAMES utf8mb4;

INSERT INTO main_features
  (feature_id, feature_name, feature_code, group_code, feature_description, created_by, updated_by, created_at, updated_at)
VALUES
  (1, 'EMPTY_PARAGRAPH', 1001, 1000, 'Empty paragraphs', 0, 0, NOW(), NOW()),
  (2, 'SECTION_PAGE_COLUMN_BREAK', 1002, 1000, 'Section, page, column breaks', 0, 0, NOW(), NOW()),
  (3, 'SPACE_TAB_SPACE', 1003, 1000, 'Space after/before tab space', 0, 0, NOW(), NOW()),
  (4, 'SPACE_START_END_PARAGRAPH', 1004, 1000, 'Space at the start/end of the paragraph', 0, 0, NOW(), NOW()),
  (5, 'SPACE_BEFORE_PUNCTUATION', 1005, 1000, 'Space before punctuation', 0, 0, NOW(), NOW()),
  (6, 'SPACE_AFTER_OPENING_PARANTHESES', 1006, 1000, 'Space after opening parentheses', 0, 0, NOW(), NOW()),
  (7, 'SPACE_BEFORE_CLOSING_PARANTHESES', 1007, 1000, 'Space before closing parentheses', 0, 0, NOW(), NOW()),
  (8, 'REMOVE_HYPERLINKS_FIELDCODES', 1008, 1000, 'Removes hyperlinks and field codes', 0, 0, NOW(), NOW()),
  (9, 'NONBREAKINGSPACE_TO_NORMALSPACE', 1009, 1000, 'Non-breaking space to normal space', 0, 0, NOW(), NOW()),
  (10, 'SERIAL_COMMAS', 2001, 2000, 'Serial commas have been used consistently', 0, 0, NOW(), NOW()),
  (11, 'PUNCTUATION_BOLD_ITALIC', 2002, 2000, 'Punctuation is not bold or italic, even if it follows a bold or italic word in text', 0, 0, NOW(), NOW()),
  (12, 'EN_RULES', 2003, 2000, 'En-rules have been used for spans of numbers (e.g. 20–40), not hyphen, including page numbers in references', 0, 0, NOW(), NOW()),
  (13, 'EN_EM_Dash', 2004, 2000, 'Space en-dash or em-dash is used for parenthetical dashes', 0, 0, NOW(), NOW()),
  (14, 'SENTENCE_END_FULLSTOP', 2005, 2000, 'Each complete sentence is ending with a full stop', 0, 0, NOW(), NOW()),
  (15, 'QUOTE_MARK', 2006, 2000, 'Each opening quote mark has a corresponding closing quote mark and vice versa', 0, 0, NOW(), NOW()),
  (16, 'PARANTHESIS', 2007, 2000, 'Each opening parenthesis has a closing parenthesis and vice versa', 0, 0, NOW(), NOW()),
  (17, 'QUOTATION_MARK_CONSISTENCY', 2008, 2000, 'Use of single or double quotations marks is made consistent', 0, 0, NOW(), NOW()),
  (18, 'PUNCTUATION_MARK_QUOTATION_MARK', 2009, 2000, 'Punctuation marks are place inside or outside the quotation marks. e.g.', 0, 0, NOW(), NOW()),
  (19, 'FOURTH_PERIOD', 2010, 2000, 'Fourth period added to indicate the end of the sentence when an ellipsis ends a sentence', 0, 0, NOW(), NOW()),
  (20, 'BULLETED_NUMBEREDLIST_PARALLEL_FORM', 3001, 3000, 'The list items are either complete sentences or phrases or single words – and they start with same parts of speech, e.g. noun, verb, gerund.', 0, 0, NOW(), NOW()),
  (21, 'LIST_ITEM', 3002, 3000, 'Lists contain at least two items.', 0, 0, NOW(), NOW()),
  (22, 'NUMBERED_LIST_SEQUENTIAL', 3003, 3000, 'Numbered lists are sequential (i.e., no missing or duplicated numbers) and formatting isconsistent.', 0, 0, NOW(), NOW()),
  (23, 'PERIOD_ENDOF_LIST_FULL_SENTENCE', 3004, 3000, 'Period at the end of the sentences in lists if full sentence', 0, 0, NOW(), NOW()),
  (24, 'PERIOD_ENDOF_LIST_FULL_SENTENCE_WITH_STEM', 3005, 3000, 'Period at the end of the sentences in lists if full sentence', 0, 0, NOW(), NOW()),
  (25, 'PERIOD_ENDOF_LIST_INCOMPLETE_SENTENCE', 3006, 3000, 'NO Period at the end of the lists if all incomplete sentence', 0, 0, NOW(), NOW()),
  (26, 'ACRONYMS_SPELLED_OUT_FIRST_INSTANCE', 4001, 4000, 'All acronyms (unless it is very common or would be known by readers) are spelled out at the first instance.', 0, 0, NOW(), NOW()),
  (27, 'FULL_STOP_AFTER_ORGANIZATION', 4002, 4000, 'No full stops for company or institution abbreviations, e.g. UN, BBC, GB.', 0, 0, NOW(), NOW()),
  (28, 'FULL_STOP_AFTER_ABBREVIATION', 4003, 4000, 'Full stop for abbreviations: Mr, Dr, am, pm.', 0, 0, NOW(), NOW()),
  (29, 'LOWERCASE_S_FOR_PLURAL', 4004, 4000, 'Lowercase “s” added to indicate plural not apostrophe, e.g., SMEs', 0, 0, NOW(), NOW()),
  (30, 'THINSPACE_BETWEEN_INITIALS', 4005, 4000, 'Thin Space between initials: C. S. Lewis', 0, 0, NOW(), NOW()),
  (31, 'GERUNDS_PROCEDURE_HEADINGS', 5001, 5000, 'Gerunds are used for procedure headings, e.g. Installing the software.', 0, 0, NOW(), NOW()),
  (32, 'HEADING_CONSISTENCY', 5002, 5000, 'Style and formatting of different levels of headings is consistent.', 0, 0, NOW(), NOW()),
  (33, 'ARTICLE_TITLE_IDENTIFICATION', 5003, 5000, 'Mark article title', 0, 0, NOW(), NOW()),
  (34, 'AUTHOR_IDENTIFICATION', 5004, 5000, 'Mark authors', 0, 0, NOW(), NOW()),
  (35, 'KEYWORD_IDENTIFICATION', 5005, 5000, 'Mark keywords', 0, 0, NOW(), NOW()),
  (36, 'ABBREVIATION_IDENTIFICATION', 5006, 5000, 'Mark Abbreviation', 0, 0, NOW(), NOW()),
  (37, 'HEADING_IDENTIFICATION', 5007, 5000, 'Mark Headings', 0, 0, NOW(), NOW()),
  (38, 'ABSTRACT_IDENTIFICATION', 5008, 5000, 'Mark Abstract', 0, 0, NOW(), NOW()),
  (39, 'GRAPHICAL_ABSTRACT_IDENTIFICATION', 5009, 5000, 'Mark Graphical Abstract', 0, 0, NOW(), NOW()),
  (40, 'ABSTRACT_SECTION_IDENTIFICATION', 5010, 5000, 'Mark Abstract Section', 0, 0, NOW(), NOW()),
  (41, 'HIGLIGHT_IDENTIFICATION', 5011, 5000, 'Mark  Highlights', 0, 0, NOW(), NOW()),
  (42, 'CORRESPONDING_AUTHOR', 5012, 5000, 'Mark corresponding author', 0, 0, NOW(), NOW()),
  (43, 'SHORTTITLE', 5013, 5000, 'Mark Short Title', 0, 0, NOW(), NOW()),
  (44, 'COLLABRATION', 5014, 5000, 'Mark Collabration', 0, 0, NOW(), NOW()),
  (45, 'AFFILIATION', 5015, 5000, 'Mark Affiliation', 0, 0, NOW(), NOW()),
  (46, 'AFFILIATION_DATA', 5016, 5000, 'Get Affiliation Data', 0, 0, NOW(), NOW()),
  (47, 'AFFILIATION_CLONING', 5017, 5000, 'Affiliation cloning', 0, 0, NOW(), NOW()),
  (48, 'Asubtitle_IDENTIFICATION', 5018, 5000, 'Mark Asubtitle', 0, 0, NOW(), NOW()),
  (49, 'PRESENT_CURRENT_ADDRESS', 5019, 5000, 'Mark Present & Current Address', 0, 0, NOW(), NOW()),
  (50, 'ARTICLE_FOOTNOTE', 5020, 5000, 'Mark article footnote', 0, 0, NOW(), NOW()),
  (51, 'EMAIL_IDENTIFICATION', 5021, 5000, 'Highlight Email', 0, 0, NOW(), NOW()),
  (52, 'SUPPLEMENTARY_MATERIAL', 5022, 5000, 'Highlight supplementary Material', 0, 0, NOW(), NOW()),
  (53, 'NUMBERS_LESS_THAN_10_SPELLED_OUT', 6001, 6000, 'Numbers less than 10 are spelled out, and numerals are used for numbers >= 10.(Exceptions to this would be measurements, temperature readings, percentages, and so on, e.g. 3cm, 3.10 kg, 5%.)', 0, 0, NOW(), NOW()),
  (54, 'WRITTEN_OUT_NUMBER_HYPHENATED', 6002, 6000, 'Written-out numbers and fractions are hyphenated as necessary, e.g. twenty-one, forty-four,two-thirds.', 0, 0, NOW(), NOW()),
  (55, 'NUMERALS_FOR_ABBREVIATIONS', 6003, 6000, 'Numerals are used with abbreviations and symbols, e.g., 5 kg, 6%.', 0, 0, NOW(), NOW()),
  (56, 'NUMBER_GREATER_THAN_10', 6004, 6000, 'Greater than 10 rule is used consistently – If numbers both greater and less than 10 appear in the same sentence, numerals are used for all. (For example: There were 5 mangoes and 12 oranges in the basket.)', 0, 0, NOW(), NOW()),
  (57, 'THOUSAND_SEPARATOR', 6005, 6000, 'Thousand separator is used consistently in four-digit numbers, e.g., 1,000kilograms.', 0, 0, NOW(), NOW()),
  (58, 'ORDINALS_ITALICIZED', 6006, 6000, 'In ordinals formed with letters, the letter is italicized but the suffix is roman, e.g. nth.  nth(n in italic)', 0, 0, NOW(), NOW()),
  (59, 'date range in full', 7001, 7000, 'Date ranges in full, e.g. 2008–2009 (years given in full)', 0, 0, NOW(), NOW()),
  (60, 'year in full', 7002, 7000, '☐ Year in the 1980s, not in 80s', 0, 0, NOW(), NOW()),
  (61, 'century in digit', 7003, 7000, 'Century in 19th century not in nineteenth century', 0, 0, NOW(), NOW()),
  (62, 'punctuation in time', 7004, 7000, 'Time format 9:30 am/10 pm; default: 9:30 a.m./10 p.m.', 0, 0, NOW(), NOW()),
  (63, 'casing of words', 8001, 8000, 'Consistent casing of words, especially technical terms, has been maintained.', 0, 0, NOW(), NOW()),
  (64, 'heading capitalization', 8002, 8000, 'In chapter titles, section headings, table captions, etc., where Title Case / Initial Caps has been used, articles (a, an, the), coordinating conjunctions (and, but, for), and prepositions of less than five letters are not capitalised.', 0, 0, NOW(), NOW()),
  (65, 'Spell Checking', 1, 0, '', 0, 0, NOW(), NOW()),
  (66, 'Uniform spellings', 9001, 9000, 'Either UK or US or Oxford Dictionary spellings are applied consistently.', 0, 0, NOW(), NOW()),
  (67, 'remove gender bias', 9002, 9000, 'Gender-neutral language: to remove gender bias, plural nouns and pronouns are used, or the sentence restructured by amending his or her to their (unless related to a named individual).', 0, 0, NOW(), NOW()),
  (68, 'Phrasal verb hyphenation', 9003, 9000, 'Phrasal verbs are hyphenated, e.g. follow-up, sign-in.', 0, 0, NOW(), NOW()),
  (69, 'Placing of adverbs', 9004, 9000, 'Avoid unsightly adverbs, that is, adverbs are placed as close as possible to verbs.', 0, 0, NOW(), NOW()),
  (70, 'Double negative sentence constructions', 9005, 9000, 'Avoid double negative sentence constructions, e.g. unclear instead of not clear.', 0, 0, NOW(), NOW()),
  (71, 'Article usages', 9006, 9000, 'Ensure correct article usage. Check for missing articles, especially the definite article the.', 0, 0, NOW(), NOW()),
  (72, 'Subject-verb agreement.', 9007, 9000, 'Subject-verb agreement.', 0, 0, NOW(), NOW()),
  (73, 'global edit after author query', 9008, 9000, 'No global edits are done without inserting a query for the author and/or emailing (e.g., do NOTchange vs. to versus when the author has consistently used vs.).', 0, 0, NOW(), NOW()),
  (74, 'Incomplete sentence', 9009, 9000, 'Incomplete or nonsensical sentences are queried for clarification.', 0, 0, NOW(), NOW()),
  (75, 'Spell check execution', 9010, 9000, 'Spell check has been run.', 0, 0, NOW(), NOW()),
  (76, 'Quotation reference', 10001, 10000, 'All quotations are fully referenced, including page numbers.', 0, 0, NOW(), NOW()),
  (77, 'Quotation enclosure', 10002, 10000, 'Quotations (of more than 50 words) are not enclosed in quotation marks and start at a new line.', 0, 0, NOW(), NOW()),
  (78, 'En and Em rules in Quotation', 10003, 10000, 'En and em rules in quotations are corrected to match book style.', 0, 0, NOW(), NOW()),
  (79, 'Art queries', 11001, 11000, 'All art is accounted for or queried', 0, 0, NOW(), NOW()),
  (80, 'ART copy edited', 11002, 11000, 'All elements of art are copyedited for consistency with the surrounding text.', 0, 0, NOW(), NOW()),
  (81, 'Figure callout', 11003, 11000, 'Each figure has a number and a caption following the callout.', 0, 0, NOW(), NOW()),
  (82, 'Capitalization of figure captions', 11004, 11000, 'Capitalization of figure captions is consistent (ALL CAPS ☐, or Title Case ☐, or Sentencecase).', 0, 0, NOW(), NOW()),
  (83, 'fullstop after figure caption', 11005, 11000, '☐ Full stop or not ☐ after figure captions.', 0, 0, NOW(), NOW()),
  (84, 'table number and title', 11006, 11000, '☐ Each table has a number and a title.', 0, 0, NOW(), NOW()),
  (85, 'Capitalization of Table Captions', 11007, 11000, '☐ Capitalization of table captions is consistent (ALL CAPS ☐, or Title Case ☐, or Sentencecase).', 0, 0, NOW(), NOW()),
  (86, 'Full stop', 11008, 11000, '☐ Full stop or not ☐ after table captions.', 0, 0, NOW(), NOW()),
  (87, 'Source note bottom of figure_tables', 11009, 11000, '☐ Source notes at the bottom of figures and tables are consistently formatted.', 0, 0, NOW(), NOW()),
  (88, 'footnotes', 11010, 11000, 'Following symbols are used in the order shown to indicate footnotes: *, †, ‡, §, ¶, #.', 0, 0, NOW(), NOW());

ALTER TABLE main_features AUTO_INCREMENT = 89;