PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    school_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Student', 'Faculty', 'Clinic Staff', 'Clinic Personnel', 'Administrator')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recurring_schedule_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 200),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (service, start_time, end_time),
    CHECK (start_time < end_time)
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 200),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    template_id INTEGER REFERENCES recurring_schedule_templates(id),
    CHECK (start_time < end_time)
);

CREATE INDEX IF NOT EXISTS idx_schedules_date_active ON schedules (date, active);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    schedule_id INTEGER NOT NULL REFERENCES schedules(id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Cancelled', 'Checked-In', 'Completed')),
    created_at TEXT NOT NULL,
    reviewed_by INTEGER REFERENCES users(id),
    review_reason TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_appointments_user_created ON appointments (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_appointments_schedule_status ON appointments (schedule_id, status);

CREATE TABLE IF NOT EXISTS login_attempts (
    rate_key TEXT PRIMARY KEY,
    failed_count INTEGER NOT NULL CHECK (failed_count >= 1),
    first_failed_at TEXT NOT NULL,
    locked_until TEXT
);