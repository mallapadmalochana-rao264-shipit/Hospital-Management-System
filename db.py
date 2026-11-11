import os
import sqlite3
from datetime import date, timedelta

from flask import g, current_app
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

_mongo_db = None
_mongo_mode = "Not connected"


# ---------------------------------------------------------------- SQLite
def get_sql():
    """One SQLite connection per request (stored in Flask's g)."""
    if "sql" not in g:
        conn = sqlite3.connect(current_app.config["SQLITE_PATH"])
        conn.row_factory = sqlite3.Row          # access columns by name
        conn.execute("PRAGMA foreign_keys = ON")  # enforce foreign keys
        g.sql = conn
    return g.sql


def close_sql(exc=None):
    conn = g.pop("sql", None)
    if conn is not None:
        conn.close()


def init_sqlite(app):
    """Create tables from schema.sql and insert sample data on first run."""
    db_path = app.config["SQLITE_PATH"]
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(app.root_path, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_appointment_patient ON appointment(patient_id);
        CREATE INDEX IF NOT EXISTS idx_appointment_doctor_date ON appointment(doctor_id, appt_date);
        CREATE INDEX IF NOT EXISTS idx_bill_patient_date ON bill(patient_id, bill_date);
        CREATE INDEX IF NOT EXISTS idx_doctor_department ON doctor(dept_id);
    """)
    if conn.execute("SELECT COUNT(*) FROM admin").fetchone()[0] == 0:
        seed_sqlite(conn)
    conn.commit()
    conn.close()


def seed_sqlite(conn):
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    conn.execute("INSERT INTO admin(username, password_hash) VALUES (?, ?)",
                 (username, generate_password_hash(password)))

    conn.executemany(
        "INSERT INTO department(dept_name, location, phone) VALUES (?,?,?)",
        [("Cardiology", "Block A, Floor 2", "0801111001"),
         ("Neurology", "Block B, Floor 1", "0801111002"),
         ("Orthopedics", "Block C, Floor 3", "0801111003"),
         ("Pediatrics", "Block A, Floor 1", "0801111004")])

    conn.executemany(
        "INSERT INTO doctor(name, specialization, phone, email, dept_id, consultation_fee) "
        "VALUES (?,?,?,?,?,?)",
        [("Dr. Ananya Rao", "Cardiologist", "9876500001", "ananya.rao@hms.com", 1, 800),
         ("Dr. Rahul Mehta", "Neurologist", "9876500002", "rahul.mehta@hms.com", 2, 900),
         ("Dr. Priya Nair", "Orthopedic Surgeon", "9876500003", "priya.nair@hms.com", 3, 700),
         ("Dr. Karthik Iyer", "Pediatrician", "9876500004", "karthik.iyer@hms.com", 4, 500)])

    conn.executemany(
        "INSERT INTO patient(name, age, gender, phone, blood_group, address) VALUES (?,?,?,?,?,?)",
        [("Vedesh Reddy", 45, "Male", "9123400001", "B+", "Indiranagar, Bengaluru"),
         ("Sneha Reddy", 32, "Female", "9123400002", "O+", "Whitefield, Bengaluru"),
         ("Samuel Benjamin", 28, "Male", "9123400003", "A+", "Koramangala, Bengaluru"),
         ("Meera Joshi", 6, "Female", "9123400004", "AB+", "Jayanagar, Bengaluru"),
         ("Malla Pradeep", 21, "Male", "9123400005", "O-", "Malleshwaram, Bengaluru"),
         ("Divya Joshi", 39, "Female", "9123400006", "B-", "HSR Layout, Bengaluru")])

    conn.executemany(
        "INSERT INTO appointment(patient_id, doctor_id, appt_date, appt_time, reason, status) "
        "VALUES (?,?,?,?,?,?)",
        [(1, 1, d(0), "10:00", "Chest pain checkup", "Scheduled"),
         (2, 2, d(0), "11:30", "Recurring migraine", "Scheduled"),
         (3, 3, d(1), "09:30", "Knee pain", "Scheduled"),
         (4, 4, d(-2), "16:00", "Fever and cough", "Completed"),
         (5, 1, d(-5), "12:00", "BP follow-up", "Completed"),
         (6, 2, d(-1), "15:15", "Dizziness", "Cancelled")])

    conn.executemany(
        "INSERT INTO bill(patient_id, appointment_id, amount, bill_date, status, description) "
        "VALUES (?,?,?,?,?,?)",
        [(4, 4, 500, d(-2), "Paid", "Consultation fee"),
         (5, 5, 800, d(-5), "Paid", "Consultation fee"),
         (1, 1, 1500, d(0), "Pending", "Consultation + ECG"),
         (2, None, 900, d(0), "Pending", "Consultation fee"),
         (3, None, 2200, d(1), "Pending", "X-ray and consultation")])


# --------------------------------------------------------------- MongoDB
def get_mongo():
    """Return the MongoDB database (Atlas if reachable, else in-memory demo)."""
    global _mongo_db, _mongo_mode
    if _mongo_db is not None:
        return _mongo_db

    cfg = current_app.config
    client = None
    if cfg["MONGO_URI"]:
        try:
            client = MongoClient(cfg["MONGO_URI"], serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            _mongo_mode = "Atlas"
            print("[MongoDB] Connected to Atlas")
        except Exception as exc:
            print("[MongoDB] Atlas unavailable, using in-memory demo:", exc)
            client = None
    if client is None:
        import mongomock
        client = mongomock.MongoClient()
        _mongo_mode = "In-memory demo"
        print("[MongoDB] Using in-memory mongomock")

    _mongo_db = client[cfg["MONGO_DB"]]
    # patient_id and doctor_id are logical references to the SQLite database.
    for collection in ("medical_records", "prescriptions", "lab_reports"):
        _mongo_db[collection].create_index([("patient_id", 1)])
        _mongo_db[collection].create_index([("doctor_id", 1)])
    _mongo_db["medical_records"].create_index([("visit_date", -1)])
    _mongo_db["prescriptions"].create_index([("date", -1)])
    _mongo_db["lab_reports"].create_index([("date", -1)])
    return _mongo_db


def mongo_mode():
    return _mongo_mode


def seed_mongo():
    """Insert sample documents. patient_id / doctor_id reference SQLite rows."""
    db = get_mongo()
    if db.medical_records.count_documents({}) > 0:
        return
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()

    db.medical_records.insert_many([
        {"patient_id": 1, "doctor_id": 1, "visit_date": d(-10),
         "diagnosis": "Hypertension (Stage 1)",
         "symptoms": ["chest pain", "headache", "fatigue"],
         "vitals": {"bp": "150/95", "temp": "98.4", "pulse": 88},
         "notes": "Advised lifestyle changes and regular BP monitoring."},
        {"patient_id": 2, "doctor_id": 2, "visit_date": d(-7),
         "diagnosis": "Migraine with aura",
         "symptoms": ["severe headache", "light sensitivity", "nausea"],
         "vitals": {"bp": "118/76", "temp": "98.2", "pulse": 74},
         "notes": "MRI recommended to rule out other causes."},
        {"patient_id": 4, "doctor_id": 4, "visit_date": d(-2),
         "diagnosis": "Viral fever",
         "symptoms": ["fever", "cough", "body ache"],
         "vitals": {"bp": "95/60", "temp": "101.2", "pulse": 104},
         "notes": "Rest, fluids and paracetamol. Review if fever persists."},
        {"patient_id": 5, "doctor_id": 1, "visit_date": d(-5),
         "diagnosis": "Controlled hypertension",
         "symptoms": ["occasional dizziness"],
         "vitals": {"bp": "132/84", "temp": "98.6", "pulse": 76},
         "notes": "Continue current medication."},
    ])

    db.prescriptions.insert_many([
        {"patient_id": 1, "doctor_id": 1, "date": d(-10),
         "medicines": [
             {"name": "Amlodipine", "dosage": "5 mg once daily", "duration": "30 days"},
             {"name": "Aspirin", "dosage": "75 mg after lunch", "duration": "30 days"}],
         "advice": "Low-salt diet and 30 minutes of walking daily."},
        {"patient_id": 2, "doctor_id": 2, "date": d(-7),
         "medicines": [
             {"name": "Sumatriptan", "dosage": "50 mg at onset of attack", "duration": "As needed"},
             {"name": "Propranolol", "dosage": "20 mg twice daily", "duration": "60 days"}],
         "advice": "Avoid triggers like bright light and skipped meals."},
        {"patient_id": 4, "doctor_id": 4, "date": d(-2),
         "medicines": [
             {"name": "Paracetamol syrup", "dosage": "5 ml every 6 hours", "duration": "3 days"},
             {"name": "ORS", "dosage": "After every loose stool", "duration": "3 days"}],
         "advice": "Plenty of fluids and rest."},
    ])

    db.lab_reports.insert_many([
        {"patient_id": 1, "doctor_id": 1, "date": d(-9), "test_name": "Lipid Profile",
         "status": "Completed",
         "results": [
             {"parameter": "Total Cholesterol", "value": "235", "unit": "mg/dL", "range": "< 200"},
             {"parameter": "LDL", "value": "150", "unit": "mg/dL", "range": "< 100"},
             {"parameter": "HDL", "value": "42", "unit": "mg/dL", "range": "> 40"}],
         "remarks": "Borderline high cholesterol."},
        {"patient_id": 4, "doctor_id": 4, "date": d(-2), "test_name": "Complete Blood Count",
         "status": "Completed",
         "results": [
             {"parameter": "Hemoglobin", "value": "12.1", "unit": "g/dL", "range": "11.5-15.5"},
             {"parameter": "WBC", "value": "11800", "unit": "/uL", "range": "4500-11000"}],
         "remarks": "Mild leukocytosis, consistent with viral infection."},
        {"patient_id": 2, "doctor_id": 2, "date": d(0), "test_name": "MRI Brain",
         "status": "Pending", "results": [], "remarks": "Scan scheduled."},
    ])
