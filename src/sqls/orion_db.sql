-- ==========================================
-- ORION PLATFORM DATABASE SCHEMA
-- ==========================================

CREATE DATABASE IF NOT EXISTS orion_db;

USE orion_db;


-- ==========================================
-- ORGANIZATIONS
-- ==========================================

CREATE TABLE organizations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT NULL,
    updated_by INT NULL
);


-- ==========================================
-- USERS TABLE
-- ==========================================

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    organization_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT NULL,
    updated_by INT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);


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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE books
ADD COLUMN organization_id INT,
ADD FOREIGN KEY (organization_id) REFERENCES organizations(id);


CREATE TABLE inventory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    book_id INT,
    warehouse VARCHAR(100),
    quantity INT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books(id)
);

ALTER TABLE inventory
ADD COLUMN organization_id INT;

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
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (distributor_id) REFERENCES distributors(id)
);
ALTER TABLE sales
ADD COLUMN organization_id INT;


CREATE TABLE returns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    book_id INT,
    distributor_id INT,
    quantity INT,
    return_date DATE,
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (distributor_id) REFERENCES distributors(id)
);

CREATE TABLE payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    distributor_id INT,
    amount DECIMAL(10,2),
    payment_date DATE,
    FOREIGN KEY (distributor_id) REFERENCES distributors(id)
);

ALTER TABLE returns ADD COLUMN organization_id INT;
ALTER TABLE payments ADD COLUMN organization_id INT;

-- ==========================================
-- SAMPLE 
-- ==========================================

insert into organizations(name) values("Orion");
insert into organizations(name) values("Elsevier");
insert into organizations(name) values("Wiley");

insert into users(email,password_hash,organization_id)values('test@gmail.com','12345678',1)

INSERT INTO books (title, subject, isbn, price) VALUES
('Math Class 10', 'Math', 'ISBN001', 250),
('Science Class 10', 'Science', 'ISBN002', 300),
('Hindi Vyakaran', 'Hindi', 'ISBN003', 200);

INSERT INTO inventory (book_id, warehouse, quantity) VALUES
(1, 'Delhi Warehouse', 500),
(2, 'Delhi Warehouse', 200),
(3, 'Delhi Warehouse', 50);

INSERT INTO distributors (name, city, phone) VALUES
('Rama Book Depot', 'Meerut', '9876543210'),
('Goyal Bros', 'Meerut', '9123456780'),
('Patna Distributors', 'Patna', '9988776655');

INSERT INTO sales (book_id, distributor_id, quantity, total_amount, sale_date) VALUES
(1, 1, 100, 25000, '2026-04-01'),
(2, 2, 50, 15000, '2026-04-01'),
(1, 3, 150, 37500, '2026-04-02');

INSERT INTO payments (distributor_id, amount, payment_date) VALUES
(1, 10000, '2026-04-02'),
(2, 5000, '2026-04-02');

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
-- ACCESSIBILITY MASTER CHECKS
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


-- ==========================================
-- ORG + PROJECT ACCESSIBILITY CHECKS
-- ==========================================

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

