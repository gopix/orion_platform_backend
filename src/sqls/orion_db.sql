-- ==========================================
-- ORION PLATFORM DATABASE SCHEMA
-- ==========================================

CREATE DATABASE IF NOT EXISTS orion_db;

USE orion_db;

-- ==========================================
-- USERS TABLE
-- ==========================================

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    created_by INT NULL,
    updated_by INT NULL
);


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
-- ORGANIZATION USERS
-- ==========================================

CREATE TABLE organization_users (
    id INT AUTO_INCREMENT PRIMARY KEY,

    organization_id INT NOT NULL,
    user_id INT NOT NULL,
    role VARCHAR(50),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    created_by INT NULL,
    updated_by INT NULL,

    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

