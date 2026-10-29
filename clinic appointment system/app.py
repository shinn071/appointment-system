import hmac
import hashlib
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, time as clock_time, timedelta, timezone
from functools import wraps
from pathlib import Path

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from firebase_admin.exceptions import FirebaseError
from flask import Flask, g, jsonify, request, send_from_directory, session
from google.auth.exceptions import GoogleAuthError
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env.local")
INSTANCE = ROOT / "instance"
DEFAULT_DATABASE = INSTANCE / "campus_clinic.sqlite3"
DATABASE = Path(os.environ.get("CAMPUS_CLINIC_DATABASE", DEFAULT_DATABASE))
ROLES = ("Student", "Faculty", "Clinic Staff", "Clinic Personnel", "Administrator")
STATUSES = ("Pending", "Approved", "Rejected", "Cancelled", "Checked-In", "Completed")
SERVICES = (
    "General Consultation",
    "Basic Health Screening",
    "Dental Cleaning",
    "Tooth Extraction (bunot)",
    "Medical Certificate / Health Assessment Request",
    "Dental Consultation and Checkup",
)
WEEKDAY_SCHEDULE_TEMPLATES = (
    ("General Consultation", "08:00", "12:00", 10),
    ("Basic Health Screening", "08:00", "12:00", 20),
    ("Dental Cleaning", "13:00", "17:00", 20),
    ("Dental Consultation and Checkup", "13:00", "17:00", 10),
    ("Tooth Extraction (bunot)", "15:00", "17:00", 10),
    ("Medical Certificate / Health Assessment Request", "10:00", "12:00", 10),
)
SCHEDULE_HORIZON_DAYS = 90
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
SCHEMA = ROOT / "database_schema.sql"


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static")
    app.config.update(
        SECRET_KEY=os.environ.get("CAMPUS_CLINIC_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=str(DATABASE),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get(
            "CAMPUS_CLINIC_COOKIE_SECURE", "0"
        ) == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=64 * 1024,
        FIREBASE_API_KEY=os.environ.get("FIREBASE_API_KEY", ""),
        FIREBASE_AUTH_DOMAIN=os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
        FIREBASE_PROJECT_ID=os.environ.get("FIREBASE_PROJECT_ID", ""),
        FIREBASE_APP_ID=os.environ.get("FIREBASE_APP_ID", ""),
    )
    if test_config:
        app.config.update(test_config)

    def get_db():
        if "db" not in g:
            db_path = Path(app.config["DATABASE"])
            db_path.parent.mkdir(parents=True, exist_ok=True)
            g.db = sqlite3.connect(db_path, timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA busy_timeout = 10000")
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def initialize_database():
        with app.app_context():
            db = get_db()
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            db.execute("DROP TABLE IF EXISTS google_calendar_events")
            db.execute("DROP TABLE IF EXISTS google_calendar_connections")
            schedule_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(schedules)")
            }
            if "template_id" not in schedule_columns:
                db.execute(
                    "ALTER TABLE schedules ADD COLUMN template_id INTEGER REFERENCES recurring_schedule_templates(id)"
                )
            placeholders = ", ".join("?" for _ in SERVICES)
            db.execute(
                f"""UPDATE schedules SET active = 0
                    WHERE active = 1 AND service NOT IN ({placeholders})""",
                SERVICES,
            )
            db.executemany(
                """INSERT OR IGNORE INTO recurring_schedule_templates
                   (service, start_time, end_time, capacity, active)
                   VALUES (?, ?, ?, ?, 1)""",
                WEEKDAY_SCHEDULE_TEMPLATES,
            )
            db.execute(
                """UPDATE schedules SET template_id = (
                       SELECT id FROM recurring_schedule_templates t
                       WHERE t.service = schedules.service
                         AND t.start_time = schedules.start_time
                         AND t.end_time = schedules.end_time
                         AND t.capacity = schedules.capacity
                   )
                   WHERE template_id IS NULL AND EXISTS (
                       SELECT 1 FROM recurring_schedule_templates t
                       WHERE t.service = schedules.service
                         AND t.start_time = schedules.start_time
                         AND t.end_time = schedules.end_time
                         AND t.capacity = schedules.capacity
                   )"""
            )
            db.commit()

    initialize_database()

    def error(message, status=400):
        return jsonify({"error": message}), status

    def body():
        payload = request.get_json(silent=True)
        return payload if isinstance(payload, dict) else {}

    def clean_text(value, maximum=500):
        if not isinstance(value, str):
            return ""
        return value.strip()[:maximum]

    def valid_time_range(start, end):
        try:
            return clock_time.fromisoformat(start) < clock_time.fromisoformat(end)
        except ValueError:
            return False

    def utc_now():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def firebase_web_config():
        return {
            "apiKey": app.config["FIREBASE_API_KEY"],
            "authDomain": app.config["FIREBASE_AUTH_DOMAIN"],
            "projectId": app.config["FIREBASE_PROJECT_ID"],
            "appId": app.config["FIREBASE_APP_ID"],
        }

    def verify_firebase_id_token(id_token):
        project_id = app.config["FIREBASE_PROJECT_ID"]
        if not project_id:
            raise RuntimeError("Firebase sign-in is not configured on this server.")
        try:
            firebase_app = firebase_admin.get_app("campus-clinic-auth")
        except ValueError:
            credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            credential = (
                firebase_credentials.Certificate(credential_path)
                if credential_path
                else firebase_credentials.ApplicationDefault()
            )
            firebase_app = firebase_admin.initialize_app(
                credential,
                options={"projectId": project_id},
                name="campus-clinic-auth",
            )
        return firebase_auth.verify_id_token(
            id_token,
            app=firebase_app,
            check_revoked=True,
        )

    def schedule_is_in_future(schedule_date, start):
        try:
            scheduled_at = datetime.combine(
                date.fromisoformat(schedule_date), clock_time.fromisoformat(start)
            )
        except ValueError:
            return False
        return scheduled_at > datetime.now()

    def valid_password(password):
        return (
            isinstance(password, str)
            and 8 <= len(password) <= 128
            and any(character in "0123456789" for character in password)
            and any(not character.isalnum() and not character.isspace() for character in password)
        )

    def username_from_email(email):
        base = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower())[:48] or "campus-user"
        candidate = base
        suffix = 1
        while get_db().execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (candidate,)).fetchone():
            suffix += 1
            candidate = f"{base[:48 - len(str(suffix))]}{suffix}"
        return candidate

    def csrf_token():
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    @app.before_request
    def protect_mutations():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = session.get("csrf_token")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return error("Your session token expired. Refresh the page and try again.", 400)

    def current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        return get_db().execute(
            "SELECT id, name, email, username, school_id, role, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None or not user["active"]:
                session.clear()
                return error("Sign in to continue.", 401)
            g.user = user
            return view(*args, **kwargs)
        return wrapped

    def roles_required(*allowed_roles):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if g.user["role"] not in allowed_roles:
                    return error("You do not have permission to perform this action.", 403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def serialize_user(user):
        return {
            "id": user["id"], "name": user["name"], "email": user["email"],
            "schoolId": user["school_id"],
            "role": user["role"], "active": bool(user["active"]),
        }

    def serialize_appointment(row):
        item = {
            "dbId": row["id"],
            "id": row["reference"], "service": row["service"], "date": row["date"],
            "start": row["start_time"], "end": row["end_time"], "reason": row["reason"],
            "status": row["status"], "createdAt": row["created_at"],
            "reviewReason": row["review_reason"],
        }
        if "patient_name" in row.keys():
            item["patientName"] = row["patient_name"]
            item["patientEmail"] = row["patient_email"]
        return item

    def serialize_schedule(row):
        return {
            "id": row["id"], "service": row["service"], "date": row["date"],
            "start": row["start_time"], "end": row["end_time"],
            "capacity": row["capacity"], "remaining": max(0, row["capacity"] - row["reserved"]),
            "active": bool(row["active"]),
        }

    def schedule_query(where="", params=()):
        return get_db().execute(
            f"""SELECT s.id, s.service, s.date, s.start_time, s.end_time, s.capacity, s.active,
                       (SELECT COUNT(*) FROM appointments a
                        WHERE a.schedule_id = s.id
                        AND a.status IN ('Pending', 'Approved', 'Checked-In')) AS reserved
                FROM schedules s {where}
                ORDER BY s.date, s.start_time""",
            params,
        ).fetchall()

    def materialize_weekday_schedules():
        db = get_db()
        templates = db.execute(
            """SELECT id, service, start_time, end_time, capacity
               FROM recurring_schedule_templates WHERE active = 1"""
        ).fetchall()
        today = date.today()
        for offset in range(SCHEDULE_HORIZON_DAYS):
            schedule_date = today + timedelta(days=offset)
            if schedule_date.weekday() >= 5:
                continue
            for template in templates:
                db.execute(
                    """INSERT INTO schedules
                       (service, date, start_time, end_time, capacity, active, template_id)
                       SELECT ?, ?, ?, ?, ?, 1, ?
                       WHERE NOT EXISTS (
                           SELECT 1 FROM schedules
                           WHERE template_id = ? AND date = ?
                       )""",
                    (
                        template["service"], schedule_date.isoformat(),
                        template["start_time"], template["end_time"], template["capacity"],
                        template["id"], template["id"], schedule_date.isoformat(),
                    ),
                )
        db.commit()

    def appointment_rows():
        user = g.user
        if user["role"] in ("Clinic Staff", "Administrator"):
            return get_db().execute(
                """SELECT a.*, s.service, s.date, s.start_time, s.end_time,
                          u.name AS patient_name, u.email AS patient_email
                   FROM appointments a JOIN schedules s ON s.id = a.schedule_id
                   JOIN users u ON u.id = a.user_id
                   ORDER BY a.created_at DESC"""
            ).fetchall()
        if user["role"] == "Clinic Personnel":
            return get_db().execute(
                """SELECT a.*, s.service, s.date, s.start_time, s.end_time,
                          u.name AS patient_name, u.email AS patient_email
                   FROM appointments a JOIN schedules s ON s.id = a.schedule_id
                   JOIN users u ON u.id = a.user_id
                   WHERE s.date = ? AND a.status IN ('Approved', 'Checked-In', 'Completed')
                   ORDER BY s.start_time""",
                (date.today().isoformat(),),
            ).fetchall()
        return get_db().execute(
            """SELECT a.*, s.service, s.date, s.start_time, s.end_time
               FROM appointments a JOIN schedules s ON s.id = a.schedule_id
               WHERE a.user_id = ? ORDER BY a.created_at DESC""",
            (user["id"],),
        ).fetchall()

    @app.get("/")
    def index():
        return send_from_directory(str(ROOT), "index.html")

    @app.get("/api/session")
    def session_info():
        user = current_user()
        return jsonify({"csrfToken": csrf_token(), "user": serialize_user(user) if user and user["active"] else None})

    @app.get("/api/auth/config")
    def auth_config():
        config = firebase_web_config()
        configured = all(isinstance(value, str) and value.strip() for value in config.values())
        return jsonify({"firebaseConfig": config if configured else None})

    @app.post("/api/register")
    def register():
        data = body()
        name = clean_text(data.get("name"), 120)
        email = clean_text(data.get("email"), 254).lower()
        school_id = clean_text(data.get("schoolId"), 64)
        password = data.get("password")
        role = data.get("role")
        if not name or not EMAIL_RE.fullmatch(email) or not school_id:
            return error("Enter your name, a valid email address, and school ID.")
        if role not in ("Student", "Faculty"):
            return error("Public registration is available to students and faculty only.")
        if not valid_password(password):
            return error("Use at least 8 characters, including a number and a symbol.")
        db = get_db()
        try:
            username = username_from_email(email)
            cursor = db.execute(
                """INSERT INTO users (name, email, username, school_id, password_hash, role, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (name, email, username, school_id, generate_password_hash(password), role, utc_now().isoformat()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return error("An account with that email or school ID already exists.", 409)
        session.clear()
        session["user_id"] = cursor.lastrowid
        new_csrf_token = csrf_token()
        session.permanent = True
        user = current_user()
        return jsonify({"user": serialize_user(user), "csrfToken": new_csrf_token}), 201

    @app.post("/api/login")
    def login():
        data = body()
        identity = clean_text(data.get("identity"), 254).lower()
        password = data.get("password")
        if not EMAIL_RE.fullmatch(identity):
            return error("Enter your email address and password.", 401)
        rate_key = hashlib.sha256(
            f"{request.remote_addr or 'unknown'}:{identity}".encode("utf-8")
        ).hexdigest()
        attempt = get_db().execute(
            "SELECT failed_count, locked_until FROM login_attempts WHERE rate_key = ?",
            (rate_key,),
        ).fetchone()
        now = utc_now()
        if attempt and attempt["locked_until"] and attempt["locked_until"] > now.isoformat():
            return error("Too many sign-in attempts. Wait 15 minutes and try again.", 429)
        user = get_db().execute(
            "SELECT * FROM users WHERE lower(email) = ?",
            (identity,),
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password if isinstance(password, str) else ""):
            failed_count = (attempt["failed_count"] if attempt else 0) + 1
            locked_until = (now + timedelta(minutes=15)).isoformat() if failed_count >= 5 else None
            get_db().execute(
                """INSERT INTO login_attempts (rate_key, failed_count, first_failed_at, locked_until)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(rate_key) DO UPDATE SET
                     failed_count = excluded.failed_count,
                     first_failed_at = CASE WHEN excluded.failed_count = 1
                       THEN excluded.first_failed_at ELSE login_attempts.first_failed_at END,
                     locked_until = excluded.locked_until""",
                (rate_key, failed_count, now.isoformat(), locked_until),
            )
            get_db().commit()
            return error(
                "Too many sign-in attempts. Wait 15 minutes and try again." if failed_count >= 5
                else "The email or password is incorrect.",
                429 if failed_count >= 5 else 401,
            )
        if not user["active"]:
            return error("This account is inactive. Contact your campus clinic administrator.", 403)
        get_db().execute("DELETE FROM login_attempts WHERE rate_key = ?", (rate_key,))
        get_db().commit()
        session.clear()
        session["user_id"] = user["id"]
        new_csrf_token = csrf_token()
        session.permanent = True
        return jsonify({"user": serialize_user(user), "csrfToken": new_csrf_token})

    @app.post("/api/login/firebase")
    def firebase_login():
        project_id = app.config["FIREBASE_PROJECT_ID"].strip()
        web_configured = all(
            isinstance(value, str) and value.strip()
            for value in firebase_web_config().values()
        )
        if not project_id or not web_configured:
            return error("Firebase sign-in is not configured on this server.", 503)

        id_token = body().get("idToken")
        if not isinstance(id_token, str) or not id_token or len(id_token) > 16384:
            return error("Firebase sign-in could not be verified. Try again.", 401)
        try:
            claims = verify_firebase_id_token(id_token)
        except firebase_auth.UserDisabledError:
            return error("This Firebase account is disabled.", 403)
        except (firebase_auth.InvalidIdTokenError, firebase_auth.RevokedIdTokenError):
            return error("Firebase sign-in could not be verified. Try again.", 401)
        except (FirebaseError, GoogleAuthError, OSError, RuntimeError, ValueError):
            return error("Firebase sign-in is temporarily unavailable. Try again shortly.", 503)

        email = claims.get("email")
        if claims.get("email_verified") is not True or not isinstance(email, str):
            return error("Firebase must confirm your email address before you can sign in.", 401)
        email = email.strip().lower()
        if not EMAIL_RE.fullmatch(email):
            return error("Firebase sign-in did not provide a valid email address.", 401)

        user = get_db().execute(
            "SELECT * FROM users WHERE lower(email) = ?",
            (email,),
        ).fetchone()
        if not user:
            return error(
                "No clinic account is associated with this Firebase email. Create an account first.",
                401,
            )
        if not user["active"]:
            return error("This account is inactive. Contact your clinic administrator.", 403)

        session.clear()
        session["user_id"] = user["id"]
        new_csrf_token = csrf_token()
        session.permanent = True
        return jsonify({"user": serialize_user(user), "csrfToken": new_csrf_token})

    @app.post("/api/logout")
    @login_required
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/profile")
    @login_required
    def profile():
        return jsonify({"user": serialize_user(g.user)})

    @app.put("/api/profile")
    @login_required
    def update_profile():
        data = body()
        name = clean_text(data.get("name"), 120)
        email = clean_text(data.get("email"), 254).lower()
        if not name or not EMAIL_RE.fullmatch(email):
            return error("Enter a valid name and email address.")
        try:
            get_db().execute("UPDATE users SET name = ?, email = ? WHERE id = ?", (name, email, g.user["id"]))
            get_db().commit()
        except sqlite3.IntegrityError:
            get_db().rollback()
            return error("That email address is already registered.", 409)
        return jsonify({"user": serialize_user(current_user())})

    @app.get("/api/schedules")
    @login_required
    def schedules():
        materialize_weekday_schedules()
        rows = schedule_query(
            "WHERE s.active = 1 AND (s.date > ? OR (s.date = ? AND s.start_time > ?))",
            (date.today().isoformat(), date.today().isoformat(), datetime.now().strftime("%H:%M")),
        )
        return jsonify({"schedules": [serialize_schedule(row) for row in rows]})

    @app.post("/api/schedules")
    @roles_required("Clinic Staff", "Administrator")
    def create_schedule():
        data = body()
        service = clean_text(data.get("service"), 80)
        schedule_date = clean_text(data.get("date"), 10)
        start = clean_text(data.get("start"), 5)
        end = clean_text(data.get("end"), 5)
        capacity = data.get("capacity")
        try:
            parsed_date = date.fromisoformat(schedule_date)
        except (TypeError, ValueError):
            return error("Choose a valid schedule date.")
        if service not in SERVICES or not TIME_RE.fullmatch(start) or not TIME_RE.fullmatch(end) or not valid_time_range(start, end):
            return error("Choose a valid clinic service and time.")
        if not schedule_is_in_future(schedule_date, start) or type(capacity) is not int or not 1 <= capacity <= 200:
            return error("Check that the schedule is in the future and capacity is between 1 and 200.")
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        conflict = db.execute(
            """SELECT 1 FROM schedules
               WHERE active = 1 AND service = ? AND date = ?
                 AND start_time < ? AND end_time > ? LIMIT 1""",
            (service, schedule_date, end, start),
        ).fetchone()
        if conflict:
            db.rollback()
            return error("This service already has an overlapping schedule for that date.", 409)
        cursor = db.execute(
            """INSERT INTO schedules (service, date, start_time, end_time, capacity, active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (service, schedule_date, start, end, capacity),
        )
        db.commit()
        return jsonify({"schedule": next(serialize_schedule(row) for row in schedule_query("WHERE s.id = ?", (cursor.lastrowid,)))}), 201

    @app.put("/api/schedules/<int:schedule_id>")
    @roles_required("Clinic Staff", "Administrator")
    def update_schedule(schedule_id):
        data = body()
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        schedule = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if not schedule:
            return error("Schedule not found.", 404)
        service = clean_text(data.get("service"), 80)
        schedule_date = clean_text(data.get("date"), 10)
        start = clean_text(data.get("start"), 5)
        end = clean_text(data.get("end"), 5)
        capacity = data.get("capacity")
        active = data.get("active", True)
        try:
            parsed_date = date.fromisoformat(schedule_date)
        except (TypeError, ValueError):
            return error("Choose a valid schedule date.")
        if service not in SERVICES or not TIME_RE.fullmatch(start) or not TIME_RE.fullmatch(end) or not valid_time_range(start, end):
            return error("Choose a valid clinic service and time.")
        if not schedule_is_in_future(schedule_date, start) or type(capacity) is not int or not 1 <= capacity <= 200 or not isinstance(active, bool):
            return error("Check schedule date, time, capacity, and availability.")
        reserved = db.execute(
            "SELECT COUNT(*) FROM appointments WHERE schedule_id = ? AND status IN ('Pending', 'Approved', 'Checked-In')",
            (schedule_id,),
        ).fetchone()[0]
        if capacity < reserved:
            return error("Capacity cannot be lower than the number of reserved appointments.")
        if reserved and (
            service != schedule["service"] or schedule_date != schedule["date"]
            or start != schedule["start_time"] or end != schedule["end_time"]
        ):
            return error("A schedule with existing appointments cannot be moved or changed.")
        conflict = db.execute(
            """SELECT 1 FROM schedules
               WHERE id != ? AND active = 1 AND service = ? AND date = ?
                 AND start_time < ? AND end_time > ? LIMIT 1""",
            (schedule_id, service, schedule_date, end, start),
        ).fetchone()
        if active and conflict:
            return error("This service already has an overlapping schedule for that date.", 409)
        db.execute(
            """UPDATE schedules SET service = ?, date = ?, start_time = ?, end_time = ?, capacity = ?, active = ?
               WHERE id = ?""",
            (service, schedule_date, start, end, capacity, int(active), schedule_id),
        )
        db.commit()
        row = schedule_query("WHERE s.id = ?", (schedule_id,))[0]
        return jsonify({"schedule": serialize_schedule(row)})

    @app.get("/api/appointments")
    @login_required
    def appointments():
        return jsonify({"appointments": [serialize_appointment(row) for row in appointment_rows()]})

    @app.post("/api/appointments")
    @roles_required("Student", "Faculty")
    def create_appointment():
        data = body()
        reason = clean_text(data.get("reason"), 500)
        schedule_id = data.get("scheduleId")
        if type(schedule_id) is not int or not reason:
            return error("Choose an available schedule and enter a reason for your visit.")
        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            schedule = db.execute(
                """SELECT s.*, (SELECT COUNT(*) FROM appointments a
                   WHERE a.schedule_id = s.id AND a.status IN ('Pending', 'Approved', 'Checked-In')) AS reserved
                   FROM schedules s WHERE s.id = ? AND s.active = 1""",
                (schedule_id,),
            ).fetchone()
            if not schedule or not schedule_is_in_future(schedule["date"], schedule["start_time"]):
                db.rollback()
                return error("That schedule is no longer available.", 409)
            if schedule["reserved"] >= schedule["capacity"]:
                db.rollback()
                return error("That schedule is full. Choose another available time.", 409)
            duplicate = db.execute(
                """SELECT 1 FROM appointments
                   WHERE user_id = ? AND schedule_id = ?
                     AND status IN ('Pending', 'Approved', 'Checked-In') LIMIT 1""",
                (g.user["id"], schedule_id),
            ).fetchone()
            if duplicate:
                db.rollback()
                return error("You already have an active request for this appointment time.", 409)
            reference = f"CC-{utc_now():%Y}-{secrets.token_hex(3).upper()}"
            cursor = db.execute(
                """INSERT INTO appointments (reference, user_id, schedule_id, reason, status, created_at)
                   VALUES (?, ?, ?, ?, 'Pending', ?)""",
                (reference, g.user["id"], schedule_id, reason, utc_now().isoformat()),
            )
            db.commit()
            row = db.execute(
                """SELECT a.*, s.service, s.date, s.start_time, s.end_time FROM appointments a
                   JOIN schedules s ON s.id = a.schedule_id WHERE a.id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
        except sqlite3.IntegrityError:
            db.rollback()
            return error("The request could not be saved. Try again.", 409)
        return jsonify({"appointment": serialize_appointment(row)}), 201

    @app.post("/api/appointments/<int:appointment_id>/action")
    @login_required
    def appointment_action(appointment_id):
        data = body()
        action = clean_text(data.get("action"), 20)
        review_reason = clean_text(data.get("reason"), 500)
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT a.*, s.date, u.name AS patient_name
               FROM appointments a JOIN schedules s ON s.id = a.schedule_id
               JOIN users u ON u.id = a.user_id WHERE a.id = ?""",
            (appointment_id,),
        ).fetchone()
        if not row:
            db.rollback()
            return error("Appointment not found.", 404)
        role = g.user["role"]
        if action in ("approve", "reject"):
            if role not in ("Clinic Staff", "Administrator"):
                db.rollback()
                return error("Only clinic staff can review appointment requests.", 403)
            if row["status"] != "Pending":
                db.rollback()
                return error("Only pending requests can be reviewed.", 409)
            if action == "reject" and not review_reason:
                db.rollback()
                return error("Enter a reason before rejecting this request.")
            status = "Approved" if action == "approve" else "Rejected"
            changed = db.execute(
                """UPDATE appointments SET status = ?, reviewed_by = ?, review_reason = ?
                   WHERE id = ? AND status = 'Pending'""",
                (status, g.user["id"], review_reason if action == "reject" else "", appointment_id),
            ).rowcount
        elif action == "cancel":
            if row["user_id"] != g.user["id"] or row["status"] != "Pending":
                db.rollback()
                return error("Only your pending appointments can be cancelled.", 403)
            changed = db.execute(
                "UPDATE appointments SET status = 'Cancelled' WHERE id = ? AND status = 'Pending'",
                (appointment_id,),
            ).rowcount
        elif action == "check-in":
            if role != "Clinic Personnel" or row["status"] != "Approved" or row["date"] != date.today().isoformat():
                db.rollback()
                return error("Only today's approved appointments can be checked in by clinic personnel.", 403)
            changed = db.execute(
                "UPDATE appointments SET status = 'Checked-In' WHERE id = ? AND status = 'Approved'",
                (appointment_id,),
            ).rowcount
        elif action == "complete":
            if role != "Clinic Personnel" or row["status"] != "Checked-In":
                db.rollback()
                return error("Only checked-in visits can be completed by clinic personnel.", 403)
            changed = db.execute(
                "UPDATE appointments SET status = 'Completed' WHERE id = ? AND status = 'Checked-In'",
                (appointment_id,),
            ).rowcount
        else:
            db.rollback()
            return error("Unsupported appointment action.")
        if changed != 1:
            db.rollback()
            return error("This appointment was updated by another user. Refresh and try again.", 409)
        db.commit()
        return jsonify({"ok": True})

    @app.get("/api/dashboard")
    @login_required
    def dashboard():
        user = g.user
        db = get_db()
        if user["role"] == "Administrator":
            user_counts = db.execute(
                """SELECT COUNT(*) AS total, SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active,
                          SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) AS inactive FROM users"""
            ).fetchone()
            counts = {
                "totalUsers": user_counts["total"], "activeUsers": user_counts["active"] or 0,
                "inactiveUsers": user_counts["inactive"] or 0,
                "appointmentRequests": db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
            }
        else:
            materialize_weekday_schedules()
            rows = appointment_rows()
            today = date.today().isoformat()
            current_time = datetime.now().strftime("%H:%M")
            counts = {
                "upcoming": sum(
                    r["status"] in ("Pending", "Approved")
                    and (r["date"] > today or (r["date"] == today and r["start_time"] > current_time))
                    for r in rows
                ),
                "pending": sum(r["status"] == "Pending" for r in rows),
                "approved": sum(r["status"] == "Approved" for r in rows),
                "completed": sum(r["status"] == "Completed" for r in rows),
                "today": sum(r["date"] == today for r in rows),
                "checkedIn": sum(r["status"] == "Checked-In" and r["date"] == today for r in rows),
                "waiting": sum(r["status"] == "Approved" and r["date"] == today for r in rows),
                "availableSchedules": sum(
                    row["capacity"] > row["reserved"]
                    for row in schedule_query(
                        "WHERE s.active = 1 AND (s.date > ? OR (s.date = ? AND s.start_time > ?))",
                        (today, today, datetime.now().strftime("%H:%M")),
                    )
                ),
            }
        return jsonify({"counts": counts})

    @app.get("/api/users")
    @roles_required("Administrator")
    def users():
        rows = get_db().execute(
            "SELECT id, name, email, username, school_id, role, active FROM users ORDER BY created_at DESC"
        ).fetchall()
        return jsonify({"users": [serialize_user(row) for row in rows]})

    @app.post("/api/users")
    @roles_required("Administrator")
    def create_user():
        data = body()
        name = clean_text(data.get("name"), 120)
        email = clean_text(data.get("email"), 254).lower()
        school_id = clean_text(data.get("schoolId"), 64)
        password = data.get("password")
        role = data.get("role")
        if not name or not EMAIL_RE.fullmatch(email) or not school_id:
            return error("Enter a name, valid email address, and school or employee ID.")
        if role not in ROLES:
            return error("Choose a valid account role.")
        if not valid_password(password):
            return error("Use at least 8 characters, including a number and a symbol.")
        db = get_db()
        try:
            username = username_from_email(email)
            cursor = db.execute(
                """INSERT INTO users (name, email, username, school_id, password_hash, role, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (name, email, username, school_id, generate_password_hash(password), role, utc_now().isoformat()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return error("An account with that email or school ID already exists.", 409)
        created = db.execute(
            "SELECT id, name, email, username, school_id, role, active FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify({"user": serialize_user(created)}), 201

    @app.patch("/api/users/<int:user_id>")
    @roles_required("Administrator")
    def update_user_role(user_id):
        data = body()
        role = data.get("role")
        active = data.get("active")
        if role not in ROLES or not isinstance(active, bool):
            return error("Choose a valid role and account status.")
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        target = db.execute("SELECT id, role, active FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            db.rollback()
            return error("User not found.", 404)
        if target["role"] == "Administrator" and (role != "Administrator" or not active):
            admins = db.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'Administrator' AND active = 1"
            ).fetchone()[0]
            if admins <= 1:
                db.rollback()
                return error("The last active administrator cannot be demoted or deactivated.", 409)
        db.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, int(active), user_id))
        db.commit()
        return jsonify({"ok": True})

    @app.cli.command("create-admin")
    def create_admin():
        """Interactively create the first administrator account."""
        import getpass

        db = get_db()
        if db.execute("SELECT COUNT(*) FROM users WHERE role = 'Administrator'").fetchone()[0]:
            raise SystemExit("An administrator already exists. Assign additional roles from User Management.")
        name = input("Administrator full name: ").strip()
        email = input("Administrator email address: ").strip().lower()
        school_id = input("Administrator employee ID: ").strip()
        password = getpass.getpass("Password (8+ characters, with a number and symbol): ")
        confirm = getpass.getpass("Confirm password: ")
        if not name or not EMAIL_RE.fullmatch(email) or not school_id:
            raise SystemExit("Name, valid email, and employee ID are required.")
        if not valid_password(password) or password != confirm:
            raise SystemExit("Passwords must match, be at least 8 characters, and include a number and symbol.")
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM users WHERE role = 'Administrator'").fetchone()[0]:
                db.rollback()
                raise SystemExit("An administrator already exists. Assign additional roles from User Management.")
            db.execute(
                """INSERT INTO users (name, email, username, school_id, password_hash, role, active, created_at)
                   VALUES (?, ?, ?, ?, ?, 'Administrator', 1, ?)""",
                (name, email, username_from_email(email), school_id, generate_password_hash(password), utc_now().isoformat()),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise SystemExit("That email, username, or employee ID is already in use.") from exc
        print("Administrator account created. Sign in using the configured email address.")

    @app.cli.command("reset-password")
    def reset_password():
        """Reset an existing account password from the trusted application host."""
        import getpass

        email = input("Account email address: ").strip().lower()
        if not EMAIL_RE.fullmatch(email):
            raise SystemExit("Enter a valid email address.")

        password = getpass.getpass("New password (8+ characters, with a number and symbol): ")
        confirm = getpass.getpass("Confirm password: ")
        if not valid_password(password) or password != confirm:
            raise SystemExit("Passwords must match, be at least 8 characters, and include a number and symbol.")

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        user = db.execute(
            "SELECT id, active FROM users WHERE lower(email) = ?",
            (email,),
        ).fetchone()
        if not user:
            db.rollback()
            raise SystemExit("No account found with that email.")
        if not user["active"]:
            db.rollback()
            raise SystemExit("That account is inactive. Contact an administrator to reactivate it.")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user["id"]),
        )
        db.commit()
        print("Password updated. Sign in using the account's email address.")

    @app.cli.command("init-db")
    def init_db():
        """Initialize the database schema."""
        initialize_database()
        print(f"Database initialized at {app.config['DATABASE']}")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=3000, ssl_context="adhoc", debug=os.environ.get("FLASK_DEBUG") == "1")
