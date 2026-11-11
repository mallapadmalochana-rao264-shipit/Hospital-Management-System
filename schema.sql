PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS admin (
    admin_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS department (
    dept_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_name TEXT NOT NULL UNIQUE,
    location  TEXT,
    phone     TEXT
);

CREATE TABLE IF NOT EXISTS doctor (
    doctor_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    specialization   TEXT NOT NULL,
    phone            TEXT NOT NULL,
    email            TEXT NOT NULL UNIQUE,
    dept_id          INTEGER NOT NULL,
    consultation_fee REAL NOT NULL DEFAULT 0 CHECK (consultation_fee >= 0),
    FOREIGN KEY (dept_id) REFERENCES department(dept_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS patient (
    patient_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    age           INTEGER NOT NULL CHECK (age BETWEEN 0 AND 120),
    gender        TEXT NOT NULL CHECK (gender IN ('Male','Female','Other')),
    phone         TEXT NOT NULL,
    blood_group   TEXT,
    address       TEXT,
    registered_on TEXT DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS appointment (
    appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL,
    doctor_id      INTEGER NOT NULL,
    appt_date      TEXT NOT NULL,
    appt_time      TEXT NOT NULL,
    reason         TEXT,
    status         TEXT NOT NULL DEFAULT 'Scheduled'
                   CHECK (status IN ('Scheduled','Completed','Cancelled')),
    FOREIGN KEY (patient_id) REFERENCES patient(patient_id) ON DELETE CASCADE,
    FOREIGN KEY (doctor_id)  REFERENCES doctor(doctor_id)   ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS bill (
    bill_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL,
    appointment_id INTEGER,
    amount         REAL NOT NULL CHECK (amount >= 0),
    bill_date      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Paid','Pending')),
    description    TEXT,
    FOREIGN KEY (patient_id)     REFERENCES patient(patient_id)         ON DELETE CASCADE,
    FOREIGN KEY (appointment_id) REFERENCES appointment(appointment_id) ON DELETE SET NULL
);
