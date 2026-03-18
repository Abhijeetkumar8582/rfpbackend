-- Create api_credentials table (MySQL-flavored; run_migration.py contains cross-DB version)
CREATE TABLE IF NOT EXISTS api_credentials (
    id                CHAR(36) PRIMARY KEY,
    tenant_id         CHAR(36) NOT NULL,
    api_name          VARCHAR(255) NOT NULL,
    api_url           VARCHAR(1000) NULL,
    secret_key_1      TEXT NULL,
    secret_key_2      TEXT NULL,
    secret_key_3      TEXT NULL,
    secret_key_4      TEXT NULL,
    secret_key_5      TEXT NULL,
    parameter_json    JSON NULL,
    status            VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

