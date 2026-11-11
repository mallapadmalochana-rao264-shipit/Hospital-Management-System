import os
import re
import sqlite3
from datetime import date
from functools import wraps

from bson import ObjectId
from bson.errors import InvalidId
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

from config import Config
from db import (close_sql, get_mongo, get_sql, init_sqlite, mongo_mode,
                seed_mongo)

app = Flask(__name__)
app.config.from_object(Config)
app.teardown_appcontext(close_sql)

GENDERS = ["Male", "Female", "Other"]
BLOOD = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
APPT_STATUS = ["Scheduled", "Completed", "Cancelled"]
BILL_STATUS = ["Paid", "Pending"]

PATIENT_OPTS = "SELECT patient_id, name || ' (ID ' || patient_id || ')' FROM patient ORDER BY name"
DOCTOR_OPTS = "SELECT doctor_id, name || ' - ' || specialization FROM doctor ORDER BY name"
DEPT_OPTS = "SELECT dept_id, dept_name FROM department ORDER BY dept_name"
APPT_OPTS = ("SELECT a.appointment_id, '#' || a.appointment_id || ' - ' || p.name || ' - ' || a.appt_date "
             "FROM appointment a JOIN patient p ON p.patient_id = a.patient_id "
             "ORDER BY a.appointment_id DESC")

# ---------------------------------------------------------------------------
# SQLite modules (relational). One config dict drives list/add/edit/delete.
# ---------------------------------------------------------------------------
SQL_MODULES = {
    "patients": {
        "table": "patient", "pk": "patient_id", "title": "Patient",
        "plural": "Patients", "icon": "🧑",
        "select": "SELECT * FROM patient",
        "order": "patient_id DESC",
        "columns": [("patient_id", "ID"), ("name", "Name"), ("age", "Age"),
                    ("gender", "Gender"), ("phone", "Phone"), ("blood_group", "Blood")],
        "search": ["name", "phone"],
        "filter": ("gender", GENDERS), "filter_label": "Genders",
        "fields": [
            {"name": "name", "label": "Full Name", "type": "text", "required": True, "maxlength": 80},
            {"name": "age", "label": "Age", "type": "number", "required": True, "min": 0, "max": 120},
            {"name": "gender", "label": "Gender", "type": "select", "required": True, "options": GENDERS},
            {"name": "phone", "label": "Phone", "type": "tel", "required": True,
             "pattern": "[0-9]{10}", "title": "Enter a 10 digit mobile number"},
            {"name": "blood_group", "label": "Blood Group", "type": "select", "options": BLOOD},
            {"name": "address", "label": "Address", "type": "textarea", "maxlength": 200},
        ],
    },
    "doctors": {
        "table": "doctor", "pk": "doctor_id", "title": "Doctor",
        "plural": "Doctors", "icon": "🩺",
        "select": ("SELECT d.doctor_id, d.name, d.specialization, dp.dept_name AS department, "
                   "d.phone, d.email, d.consultation_fee AS fee "
                   "FROM doctor d JOIN department dp ON dp.dept_id = d.dept_id"),
        "order": "d.name",
        "columns": [("doctor_id", "ID"), ("name", "Name"), ("specialization", "Specialization"),
                    ("department", "Department"), ("phone", "Phone"), ("fee", "Fee")],
        "money": ["fee"],
        "search": ["d.name", "d.specialization", "d.email"],
        "filter": ("dp.dept_name",
                   lambda db: [r[0] for r in db.execute("SELECT dept_name FROM department ORDER BY 1")]),
        "filter_label": "Departments",
        "fields": [
            {"name": "name", "label": "Doctor Name", "type": "text", "required": True, "maxlength": 80},
            {"name": "specialization", "label": "Specialization", "type": "text", "required": True, "maxlength": 80},
            {"name": "phone", "label": "Phone", "type": "tel", "required": True,
             "pattern": "[0-9]{10}", "title": "Enter a 10 digit mobile number"},
            {"name": "email", "label": "Email", "type": "email", "required": True, "maxlength": 100},
            {"name": "dept_id", "label": "Department", "type": "select", "required": True,
             "options_sql": DEPT_OPTS, "cast": "int"},
            {"name": "consultation_fee", "label": "Consultation Fee (₹)", "type": "number",
             "required": True, "min": 0, "step": "0.01"},
        ],
    },
    "departments": {
        "table": "department", "pk": "dept_id", "title": "Department",
        "plural": "Departments", "icon": "🏢",
        "select": ("SELECT dp.dept_id, dp.dept_name, dp.location, dp.phone, "
                   "(SELECT COUNT(*) FROM doctor d WHERE d.dept_id = dp.dept_id) AS doctors "
                   "FROM department dp"),
        "order": "dp.dept_name",
        "columns": [("dept_id", "ID"), ("dept_name", "Department"), ("location", "Location"),
                    ("phone", "Phone"), ("doctors", "Doctors")],
        "search": ["dp.dept_name", "dp.location"],
        "fields": [
            {"name": "dept_name", "label": "Department Name", "type": "text", "required": True, "maxlength": 60},
            {"name": "location", "label": "Location", "type": "text", "maxlength": 80},
            {"name": "phone", "label": "Phone", "type": "tel",
             "pattern": "[0-9]{6,12}", "title": "Enter 6 to 12 digits"},
        ],
    },
    "appointments": {
        "table": "appointment", "pk": "appointment_id", "title": "Appointment",
        "plural": "Appointments", "icon": "📅",
        "select": ("SELECT a.appointment_id, p.name AS patient, d.name AS doctor, a.appt_date, "
                   "a.appt_time, a.reason, a.status FROM appointment a "
                   "JOIN patient p ON p.patient_id = a.patient_id "
                   "JOIN doctor d ON d.doctor_id = a.doctor_id"),
        "order": "a.appt_date DESC, a.appt_time DESC",
        "columns": [("appointment_id", "ID"), ("patient", "Patient"), ("doctor", "Doctor"),
                    ("appt_date", "Date"), ("appt_time", "Time"), ("reason", "Reason"),
                    ("status", "Status")],
        "search": ["p.name", "d.name", "a.reason"],
        "filter": ("a.status", APPT_STATUS), "filter_label": "Statuses",
        "fields": [
            {"name": "patient_id", "label": "Patient", "type": "select", "required": True,
             "options_sql": PATIENT_OPTS, "cast": "int"},
            {"name": "doctor_id", "label": "Doctor", "type": "select", "required": True,
             "options_sql": DOCTOR_OPTS, "cast": "int"},
            {"name": "appt_date", "label": "Date", "type": "date", "required": True},
            {"name": "appt_time", "label": "Time", "type": "time", "required": True},
            {"name": "reason", "label": "Reason", "type": "text", "maxlength": 150},
            {"name": "status", "label": "Status", "type": "select", "required": True, "options": APPT_STATUS},
        ],
    },
    "billing": {
        "table": "bill", "pk": "bill_id", "title": "Bill",
        "plural": "Billing", "icon": "💳",
        "select": ("SELECT b.bill_id, p.name AS patient, b.amount, b.bill_date, b.status, "
                   "b.description FROM bill b JOIN patient p ON p.patient_id = b.patient_id"),
        "order": "b.bill_date DESC, b.bill_id DESC",
        "columns": [("bill_id", "ID"), ("patient", "Patient"), ("amount", "Amount"),
                    ("bill_date", "Date"), ("status", "Status"), ("description", "Description")],
        "money": ["amount"],
        "search": ["p.name", "b.description"],
        "filter": ("b.status", BILL_STATUS), "filter_label": "Statuses",
        "fields": [
            {"name": "patient_id", "label": "Patient", "type": "select", "required": True,
             "options_sql": PATIENT_OPTS, "cast": "int"},
            {"name": "appointment_id", "label": "Related Appointment (optional)", "type": "select",
             "options_sql": APPT_OPTS, "cast": "int"},
            {"name": "amount", "label": "Amount (₹)", "type": "number", "required": True,
             "min": 0, "step": "0.01"},
            {"name": "bill_date", "label": "Bill Date", "type": "date", "required": True},
            {"name": "status", "label": "Payment Status", "type": "select", "required": True,
             "options": BILL_STATUS},
            {"name": "description", "label": "Description", "type": "text", "maxlength": 150},
        ],
    },
}

# ---------------------------------------------------------------------------
# MongoDB modules (documents). patient_id / doctor_id reference SQLite rows.
# ---------------------------------------------------------------------------
_PATIENT_FIELD = {"name": "patient_id", "label": "Patient", "type": "select", "required": True,
                  "options_sql": PATIENT_OPTS, "cast": "int"}
_DOCTOR_FIELD = {"name": "doctor_id", "label": "Doctor", "type": "select", "required": True,
                 "options_sql": DOCTOR_OPTS, "cast": "int"}

NOSQL_MODULES = {
    "records": {
        "collection": "medical_records", "title": "Medical Record", "plural": "Medical Records",
        "icon": "📋", "search_field": "diagnosis", "date_field": "visit_date", "sort": "visit_date",
        "fields": [
            _PATIENT_FIELD, _DOCTOR_FIELD,
            {"name": "visit_date", "label": "Visit Date", "type": "date", "required": True},
            {"name": "diagnosis", "label": "Diagnosis", "type": "text", "required": True, "maxlength": 120},
            {"name": "symptoms", "label": "Symptoms (comma separated)", "type": "text", "kind": "list"},
            {"name": "vitals.bp", "label": "Blood Pressure", "type": "text", "placeholder": "120/80",
             "pattern": "[0-9]{2,3}/[0-9]{2,3}", "title": "Use format 120/80"},
            {"name": "vitals.temp", "label": "Temperature (°F)", "type": "number",
             "min": 90, "max": 110, "step": "0.1"},
            {"name": "vitals.pulse", "label": "Pulse (bpm)", "type": "number", "min": 30, "max": 220},
            {"name": "notes", "label": "Doctor's Notes", "type": "textarea", "maxlength": 500},
        ],
    },
    "prescriptions": {
        "collection": "prescriptions", "title": "Prescription", "plural": "Prescriptions",
        "icon": "💊", "search_field": "medicines.name", "date_field": "date", "sort": "date",
        "fields": [
            _PATIENT_FIELD, _DOCTOR_FIELD,
            {"name": "date", "label": "Date", "type": "date", "required": True},
            {"name": "medicines", "label": "Medicines", "type": "textarea", "required": True, "rows": 4,
             "kind": "objects", "keys": ["name", "dosage", "duration"],
             "help": "One per line: Medicine | Dosage | Duration"},
            {"name": "advice", "label": "Advice", "type": "textarea", "maxlength": 300},
        ],
    },
    "labs": {
        "collection": "lab_reports", "title": "Lab Report", "plural": "Laboratory Reports",
        "icon": "🧪", "search_field": "test_name", "date_field": "date", "sort": "date",
        "filter": ("status", ["Pending", "Completed"]), "filter_label": "Statuses",
        "fields": [
            _PATIENT_FIELD, _DOCTOR_FIELD,
            {"name": "date", "label": "Date", "type": "date", "required": True},
            {"name": "test_name", "label": "Test Name", "type": "text", "required": True, "maxlength": 80},
            {"name": "status", "label": "Status", "type": "select", "required": True,
             "options": ["Pending", "Completed"]},
            {"name": "results", "label": "Results", "type": "textarea", "rows": 4,
             "kind": "objects", "keys": ["parameter", "value", "unit", "range"],
             "help": "One per line: Parameter | Value | Unit | Normal range"},
            {"name": "remarks", "label": "Remarks", "type": "textarea", "maxlength": 300},
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return dict(sql_modules=SQL_MODULES, nosql_modules=NOSQL_MODULES, mongo_mode=mongo_mode())


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "admin" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def resolve_options(f):
    """Return [(value, label)] for a select field (static list or SQL query)."""
    if "options" in f:
        return [(o, o) for o in f["options"]]
    if "options_sql" in f:
        return [(str(r[0]), r[1]) for r in get_sql().execute(f["options_sql"])]
    return []


def put(data, path, value):
    """put(d, 'vitals.bp', '120/80') -> d['vitals']['bp'] = '120/80' (embedded doc)."""
    parts = path.split(".")
    for p in parts[:-1]:
        data = data.setdefault(p, {})
    data[parts[-1]] = value


def validate(fields, form):
    """Server-side validation shared by SQLite and MongoDB forms."""
    data, errors = {}, []
    for f in fields:
        label, kind = f["label"], f.get("kind")
        raw = (form.get(f["name"]) or "").strip()
        if not raw:
            if f.get("required"):
                errors.append(f"{label} is required.")
            put(data, f["name"], [] if kind in ("list", "objects") else None)
            continue

        value = raw
        if f.get("maxlength") and len(raw) > f["maxlength"]:
            errors.append(f"{label} must be at most {f['maxlength']} characters.")
            continue

        t = f["type"]
        if t == "number":
            try:
                num = float(raw)
            except ValueError:
                errors.append(f"{label} must be a number.")
                continue
            if "min" in f and num < f["min"]:
                errors.append(f"{label} must be at least {f['min']}.")
                continue
            if "max" in f and num > f["max"]:
                errors.append(f"{label} must be at most {f['max']}.")
                continue
            if not f.get("step") and not num.is_integer():
                errors.append(f"{label} must be a whole number.")
                continue
            value = round(num, 2) if f.get("step") else int(num)
        elif t == "email":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
                errors.append(f"{label} is not a valid email address.")
                continue
        elif t == "date":
            try:
                date.fromisoformat(raw)
            except ValueError:
                errors.append(f"{label} is not a valid date.")
                continue
        elif t == "select":
            if raw not in [v for v, _ in resolve_options(f)]:
                errors.append(f"Please choose a valid {label}.")
                continue
            if f.get("cast") == "int":
                value = int(raw)

        if f.get("pattern") and not re.fullmatch(f["pattern"], raw):
            errors.append(f"{label}: {f.get('title', 'invalid format')}.")
            continue

        if kind == "list":
            value = [x.strip() for x in raw.split(",") if x.strip()]
        elif kind == "objects":
            rows = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                parts += [""] * (len(f["keys"]) - len(parts))
                rows.append(dict(zip(f["keys"], parts)))
            value = rows
        put(data, f["name"], value)
    return data, errors


def to_form_values(fields, doc):
    """Flatten a MongoDB document into strings for the edit form."""
    vals = {}
    for f in fields:
        cur = doc
        for p in f["name"].split("."):
            cur = cur.get(p) if isinstance(cur, dict) else None
        if f.get("kind") == "list":
            cur = ", ".join(cur or [])
        elif f.get("kind") == "objects":
            cur = "\n".join(" | ".join(str(o.get(k, "")) for k in f["keys"]) for o in (cur or []))
        vals[f["name"]] = "" if cur is None else str(cur)
    return vals


def with_options(fields):
    return [dict(f, options_list=resolve_options(f)) if f["type"] == "select" else f for f in fields]


def friendly(exc):
    msg = str(exc)
    if "UNIQUE" in msg:
        return "A record with the same unique value (name/email) already exists."
    if "FOREIGN KEY" in msg:
        return "Invalid reference: the related record does not exist or is still in use."
    return "Database error: " + msg


def name_map(table, pk, ids):
    """Look up names in SQLite for ids that came from MongoDB documents."""
    ids = list({i for i in ids if i is not None})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = get_sql().execute(f"SELECT {pk}, name FROM {table} WHERE {pk} IN ({marks})", ids)
    return {r[0]: r[1] for r in rows}


def clean(doc):
    doc["_id"] = str(doc["_id"])
    doc["id"] = doc["_id"]
    return doc


def oid(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        abort(404)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = get_sql().execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["admin"] = row["username"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard (SQLite + MongoDB numbers on one page)
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    db, mg = get_sql(), get_mongo()
    one = lambda q, p=(): db.execute(q, p).fetchone()[0]
    stats = {
        "patients": one("SELECT COUNT(*) FROM patient"),
        "doctors": one("SELECT COUNT(*) FROM doctor"),
        "departments": one("SELECT COUNT(*) FROM department"),
        "appointments": one("SELECT COUNT(*) FROM appointment"),
        "pending_bills": one("SELECT COUNT(*) FROM bill WHERE status = 'Pending'"),
        "revenue": one("SELECT COALESCE(SUM(amount), 0) FROM bill WHERE status = 'Paid'"),
        "records": mg.medical_records.count_documents({}),
        "prescriptions": mg.prescriptions.count_documents({}),
        "labs": mg.lab_reports.count_documents({}),
        "pending_labs": mg.lab_reports.count_documents({"status": "Pending"}),
    }
    upcoming = db.execute(
        """SELECT a.appointment_id, p.name AS patient, d.name AS doctor,
                  a.appt_date, a.appt_time, a.status
           FROM appointment a
           JOIN patient p ON p.patient_id = a.patient_id
           JOIN doctor d ON d.doctor_id = a.doctor_id
           WHERE a.appt_date >= ? AND a.status = 'Scheduled'
           ORDER BY a.appt_date, a.appt_time LIMIT 6""",
        (date.today().isoformat(),)).fetchall()
    rows = db.execute(
        """SELECT dp.dept_name AS name, COUNT(a.appointment_id) AS cnt
           FROM department dp
           LEFT JOIN doctor d ON d.dept_id = dp.dept_id
           LEFT JOIN appointment a ON a.doctor_id = d.doctor_id
           GROUP BY dp.dept_id ORDER BY cnt DESC""").fetchall()
    mx = max([r["cnt"] for r in rows] or [1]) or 1
    dept_load = [{"name": r["name"], "cnt": r["cnt"], "pct": int(r["cnt"] * 100 / mx)} for r in rows]
    return render_template("dashboard.html", stats=stats, upcoming=upcoming, dept_load=dept_load)


# ---------------------------------------------------------------------------
# SQLite modules: list / add / edit / delete
# ---------------------------------------------------------------------------
@app.route("/sql/<module>")
@login_required
def sql_list(module):
    mod = SQL_MODULES.get(module)
    if not mod:
        abort(404)
    db = get_sql()
    q = request.args.get("q", "").strip()
    flt = request.args.get("filter", "").strip()
    where, params, flt_opts = [], [], []
    if q:
        where.append("(" + " OR ".join(f"{c} LIKE ?" for c in mod["search"]) + ")")
        params += [f"%{q}%"] * len(mod["search"])
    if mod.get("filter"):
        col, opts = mod["filter"]
        flt_opts = opts(db) if callable(opts) else opts
        if flt:
            where.append(f"{col} = ?")
            params.append(flt)
    sql = mod["select"] + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + mod["order"]
    rows = db.execute(sql, params).fetchall()
    return render_template("list.html", module=module, mod=mod, rows=rows, q=q, flt=flt,
                           flt_opts=flt_opts)


@app.route("/sql/<module>/add", methods=["GET", "POST"])
@app.route("/sql/<module>/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def sql_form(module, rid=None):
    mod = SQL_MODULES.get(module)
    if not mod:
        abort(404)
    db = get_sql()
    values = {}
    if rid is not None:
        row = db.execute(f"SELECT * FROM {mod['table']} WHERE {mod['pk']} = ?", (rid,)).fetchone()
        if row is None:
            abort(404)
        values = {k: "" if row[k] is None else str(row[k]) for k in row.keys()}
    elif request.method == "GET":
        values = {"status": "", "bill_date": date.today().isoformat() if module == "billing" else "",
                  "appt_date": date.today().isoformat() if module == "appointments" else ""}

    if request.method == "POST":
        data, errors = validate(mod["fields"], request.form)
        values = {**values, **request.form.to_dict()}
        if not errors:
            cols = [f["name"] for f in mod["fields"]]
            try:
                if rid is None:
                    db.execute(f"INSERT INTO {mod['table']} ({','.join(cols)}) "
                               f"VALUES ({','.join('?' * len(cols))})", [data[c] for c in cols])
                else:
                    db.execute(f"UPDATE {mod['table']} SET {','.join(c + '=?' for c in cols)} "
                               f"WHERE {mod['pk']} = ?", [data[c] for c in cols] + [rid])
                db.commit()
                flash(f"{mod['title']} {'added' if rid is None else 'updated'} successfully.", "success")
                return redirect(url_for("sql_list", module=module))
            except sqlite3.IntegrityError as exc:
                db.rollback()
                errors.append(friendly(exc))
        for e in errors:
            flash(e, "danger")

    return render_template("form.html", fields=with_options(mod["fields"]), values=values,
                           heading=f"{'Edit' if rid else 'Add'} {mod['title']}",
                           back_url=url_for("sql_list", module=module))


@app.route("/sql/<module>/<int:rid>/delete", methods=["POST"])
@login_required
def sql_delete(module, rid):
    mod = SQL_MODULES.get(module)
    if not mod:
        abort(404)
    db, mg = get_sql(), get_mongo()
    colls = ("medical_records", "prescriptions", "lab_reports")
    # Cross-database integrity: MongoDB cannot be protected by SQLite foreign keys,
    # so the application enforces it.
    if module == "doctors" and any(mg[c].count_documents({"doctor_id": rid}) for c in colls):
        flash("Cannot delete: this doctor is referenced by MongoDB records/prescriptions/lab reports.",
              "danger")
        return redirect(url_for("sql_list", module=module))
    try:
        db.execute(f"DELETE FROM {mod['table']} WHERE {mod['pk']} = ?", (rid,))
        db.commit()
        if module == "patients":  # cascade into MongoDB
            for c in colls:
                mg[c].delete_many({"patient_id": rid})
        flash(f"{mod['title']} deleted.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Cannot delete: this record is used by other records (foreign key constraint).", "danger")
    return redirect(url_for("sql_list", module=module))


# ---------------------------------------------------------------------------
# MongoDB modules: list / add / edit / delete
# ---------------------------------------------------------------------------
@app.route("/nosql/<module>")
@login_required
def nosql_list(module):
    mod = NOSQL_MODULES.get(module)
    if not mod:
        abort(404)
    mg, db = get_mongo(), get_sql()
    q = request.args.get("q", "").strip()
    flt = request.args.get("filter", "").strip()
    query = {}
    if q:
        # Step 1 (SQLite): find patient ids whose name matches.
        ids = [r[0] for r in db.execute("SELECT patient_id FROM patient WHERE name LIKE ?", (f"%{q}%",))]
        # Step 2 (MongoDB): search by those ids OR by the document's own text field.
        query["$or"] = [{"patient_id": {"$in": ids}},
                        {mod["search_field"]: {"$regex": re.escape(q), "$options": "i"}}]
    if flt and mod.get("filter"):
        query[mod["filter"][0]] = flt
    docs = [clean(d) for d in mg[mod["collection"]].find(query).sort(mod["sort"], -1)]
    # Step 3: join names from SQLite into the MongoDB documents.
    pn = name_map("patient", "patient_id", [d.get("patient_id") for d in docs])
    dn = name_map("doctor", "doctor_id", [d.get("doctor_id") for d in docs])
    for d in docs:
        d["patient_name"] = pn.get(d.get("patient_id"), "Unknown patient")
        d["doctor_name"] = dn.get(d.get("doctor_id"), "Unknown doctor")
    flt_opts = mod["filter"][1] if mod.get("filter") else []
    return render_template("nosql_list.html", module=module, mod=mod, docs=docs, q=q, flt=flt,
                           flt_opts=flt_opts)


@app.route("/nosql/<module>/add", methods=["GET", "POST"])
@app.route("/nosql/<module>/<doc_id>/edit", methods=["GET", "POST"])
@login_required
def nosql_form(module, doc_id=None):
    mod = NOSQL_MODULES.get(module)
    if not mod:
        abort(404)
    coll = get_mongo()[mod["collection"]]
    values = {}
    if doc_id:
        doc = coll.find_one({"_id": oid(doc_id)})
        if doc is None:
            abort(404)
        values = to_form_values(mod["fields"], doc)
    else:
        values = {"patient_id": request.args.get("patient_id", ""),
                  "visit_date": date.today().isoformat(), "date": date.today().isoformat()}

    if request.method == "POST":
        data, errors = validate(mod["fields"], request.form)
        values = {**values, **request.form.to_dict()}
        if not errors:
            if doc_id is None:
                coll.insert_one(data)
            else:
                coll.update_one({"_id": oid(doc_id)}, {"$set": data})
            flash(f"{mod['title']} {'added' if doc_id is None else 'updated'} successfully.", "success")
            return redirect(url_for("nosql_list", module=module))
        for e in errors:
            flash(e, "danger")

    return render_template("form.html", fields=with_options(mod["fields"]), values=values,
                           heading=f"{'Edit' if doc_id else 'Add'} {mod['title']}",
                           back_url=url_for("nosql_list", module=module))


@app.route("/nosql/<module>/<doc_id>/delete", methods=["POST"])
@login_required
def nosql_delete(module, doc_id):
    mod = NOSQL_MODULES.get(module)
    if not mod:
        abort(404)
    get_mongo()[mod["collection"]].delete_one({"_id": oid(doc_id)})
    flash(f"{mod['title']} deleted.", "success")
    return redirect(url_for("nosql_list", module=module))


# ---------------------------------------------------------------------------
# Patient 360: combines SQLite rows + MongoDB documents for one patient
# ---------------------------------------------------------------------------
def patient_bundle(pid):
    db, mg = get_sql(), get_mongo()
    p = db.execute("SELECT * FROM patient WHERE patient_id = ?", (pid,)).fetchone()
    if p is None:
        return None

    # ----- SQLite part (JOINs across appointment, doctor, department) -----
    appts = [dict(r) for r in db.execute(
        """SELECT a.appointment_id, a.appt_date, a.appt_time, a.reason, a.status,
                  d.name AS doctor, dp.dept_name AS department
           FROM appointment a
           JOIN doctor d ON d.doctor_id = a.doctor_id
           JOIN department dp ON dp.dept_id = d.dept_id
           WHERE a.patient_id = ? ORDER BY a.appt_date DESC""", (pid,))]
    bills = [dict(r) for r in db.execute(
        "SELECT bill_id, amount, bill_date, status, description FROM bill "
        "WHERE patient_id = ? ORDER BY bill_date DESC", (pid,))]

    # ----- MongoDB part (documents referencing patient_id) -----
    mongo = {}
    for key, mod in NOSQL_MODULES.items():
        docs = [clean(d) for d in mg[mod["collection"]].find({"patient_id": pid}).sort(mod["sort"], -1)]
        dn = name_map("doctor", "doctor_id", [d.get("doctor_id") for d in docs])  # back to SQLite
        for d in docs:
            d["doctor_name"] = dn.get(d.get("doctor_id"), "Unknown doctor")
        mongo[key] = docs

    return {
        "patient": dict(p), "appointments": appts, "bills": bills,
        "paid": sum(b["amount"] for b in bills if b["status"] == "Paid"),
        "pending": sum(b["amount"] for b in bills if b["status"] == "Pending"),
        "records": mongo["records"], "prescriptions": mongo["prescriptions"], "labs": mongo["labs"],
    }


@app.route("/patient/<int:pid>")
@login_required
def patient_profile(pid):
    bundle = patient_bundle(pid)
    if bundle is None:
        abort(404)
    return render_template("patient_profile.html", **bundle)


@app.route("/api/patient/<int:pid>")
@login_required
def patient_api(pid):
    bundle = patient_bundle(pid)
    if bundle is None:
        abort(404)
    return jsonify(bundle)


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.errorhandler(404)
def not_found(_):
    return render_template("base.html", not_found=True), 404


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
with app.app_context():
    init_sqlite(app)
    seed_mongo()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
