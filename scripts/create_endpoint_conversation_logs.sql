-- MySQL: endpoint_logs and conversation_logs
-- Prerequisites: activity_logs and users tables must exist.

-- Endpoint logs (with activity_id)
CREATE TABLE IF NOT EXISTS endpoint_logs (
    id INT NOT NULL AUTO_INCREMENT,
    activity_id INT NULL,
    ts DATETIME NOT NULL,
    method VARCHAR(16) NOT NULL,
    path VARCHAR(1024) NOT NULL,
    status_code INT NOT NULL,
    duration_ms INT NULL,
    request_id VARCHAR(64) NULL,
    actor_user_id VARCHAR(40) NULL,
    ip_address VARCHAR(45) NULL,
    user_agent TEXT NULL,
    error_message TEXT NULL,
    PRIMARY KEY (id),
    INDEX ix_endpoint_logs_activity_id (activity_id),
    INDEX ix_endpoint_logs_request_id (request_id),
    INDEX ix_endpoint_logs_ts (ts),
    CONSTRAINT fk_endpoint_logs_activity FOREIGN KEY (activity_id) REFERENCES activity_logs (id) ON DELETE SET NULL,
    CONSTRAINT fk_endpoint_logs_user FOREIGN KEY (actor_user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Conversation logs
CREATE TABLE IF NOT EXISTS conversation_logs (
    id INT NOT NULL AUTO_INCREMENT,
    activity_id INT NULL,
    ts DATETIME NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    message_index INT NOT NULL DEFAULT 0,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    actor_user_id VARCHAR(40) NULL,
    metadata_json LONGTEXT NULL,
    PRIMARY KEY (id),
    INDEX ix_conversation_logs_activity_id (activity_id),
    INDEX ix_conversation_logs_conversation_id (conversation_id),
    INDEX ix_conversation_logs_ts (ts),
    CONSTRAINT fk_conversation_logs_activity FOREIGN KEY (activity_id) REFERENCES activity_logs (id) ON DELETE SET NULL,
    CONSTRAINT fk_conversation_logs_user FOREIGN KEY (actor_user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
