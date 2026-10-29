import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from firebase_admin import auth as firebase_auth
from firebase_admin.exceptions import FirebaseError
from werkzeug.security import check_password_hash, generate_password_hash

from app import SERVICES, create_app


class CampusClinicTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="campus-clinic-tests-")
        self.database = Path(self.temp_dir.name) / "clinic.sqlite3"
        self.app = create_app({
            "TESTING": True,
            "DATABASE": str(self.database),
            "SECRET_KEY": "test-secret-key",
            "FIREBASE_API_KEY": "test-api-key",
            "FIREBASE_AUTH_DOMAIN": "clinic-test.firebaseapp.com",
            "FIREBASE_PROJECT_ID": "clinic-test",
            "FIREBASE_APP_ID": "test-app-id",
        })
        self.client = self.app.test_client()
        self.student = self.register_student()
        self.add_user("staff", "Clinic Staff")
        self.add_user("personnel", "Clinic Personnel")
        self.add_user("admin", "Administrator")

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_token(self, client):
        return client.get("/api/session").get_json()["csrfToken"]

    def register_student(self):
        token = self.csrf_token(self.client)
        response = self.client.post(
            "/api/register",
            json={
                "name": "Test Student",
                "email": "student@personal.example",
                "schoolId": "STUDENT-1",
                "password": "Secure!123",
                "role": "Student",
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return self.client

    def add_user(self, prefix, role):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                """INSERT INTO users
                   (name, email, username, school_id, password_hash, role, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    f"Test {prefix}",
                    f"{prefix}@example.edu",
                    prefix,
                    f"{prefix.upper()}-1",
                    generate_password_hash("Secure!123"),
                    role,
                    datetime.now().isoformat(),
                ),
            )

    def login_as(self, prefix):
        client = self.app.test_client()
        token = self.csrf_token(client)
        response = client.post(
            "/api/login",
            json={"identity": f"{prefix}@example.edu", "password": "Secure!123"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return client

    def test_reset_password_command_restores_account_sign_in(self):
        runner = self.app.test_cli_runner()
        with patch("builtins.input", return_value="admin@example.edu"), patch(
            "getpass.getpass", side_effect=["Restored!123", "Restored!123"]
        ):
            result = runner.invoke(args=["reset-password"])

        self.assertEqual(result.exit_code, 0, result.output)
        with closing(sqlite3.connect(self.database)) as db:
            password_hash = db.execute(
                "SELECT password_hash FROM users WHERE email = 'admin@example.edu'"
            ).fetchone()[0]
        self.assertTrue(check_password_hash(password_hash, "Restored!123"))

        admin = self.app.test_client()
        response = admin.post(
            "/api/login",
            json={"identity": "admin@example.edu", "password": "Restored!123"},
            headers={"X-CSRF-Token": self.csrf_token(admin)},
        )
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_password_sign_in_accepts_a_personal_email_address(self):
        client = self.app.test_client()
        response = client.post(
            "/api/login",
            json={"identity": "student@personal.example", "password": "Secure!123"},
            headers={"X-CSRF-Token": self.csrf_token(client)},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["user"]["email"], "student@personal.example")

    def test_firebase_google_sign_in_requires_verified_email_and_existing_account(self):
        config = self.client.get("/api/auth/config").get_json()["firebaseConfig"]
        self.assertEqual(config["projectId"], "clinic-test")
        credential = "firebase-id-token"
        verified_claims = {
            "email": "STUDENT@PERSONAL.EXAMPLE",
            "email_verified": True,
            "uid": "firebase-user-id",
        }

        firebase_admin_app = object()
        with patch("app.firebase_admin.get_app", return_value=firebase_admin_app), patch(
            "app.firebase_auth.verify_id_token",
            return_value=verified_claims,
        ) as verify:
            response = self.student.post(
                "/api/login/firebase",
                json={"idToken": credential},
                headers={"X-CSRF-Token": self.csrf_token(self.student)},
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["user"]["email"], "student@personal.example")
        verify.assert_called_once_with(
            credential,
            app=firebase_admin_app,
            check_revoked=True,
        )

        unverified_claims = {
            "email": "student@personal.example",
            "email_verified": False,
        }
        with patch("app.firebase_admin.get_app", return_value=firebase_admin_app), patch(
            "app.firebase_auth.verify_id_token",
            return_value=unverified_claims,
        ):
            response = self.student.post(
                "/api/login/firebase",
                json={"idToken": credential},
                headers={"X-CSRF-Token": self.csrf_token(self.student)},
            )
        self.assertEqual(response.status_code, 401)

        unknown_claims = {
            "email": "new.person@personal.example",
            "email_verified": True,
        }
        with patch("app.firebase_admin.get_app", return_value=firebase_admin_app), patch(
            "app.firebase_auth.verify_id_token",
            return_value=unknown_claims,
        ):
            response = self.student.post(
                "/api/login/firebase",
                json={"idToken": credential},
                headers={"X-CSRF-Token": self.csrf_token(self.student)},
            )
        self.assertEqual(response.status_code, 401)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 4)

    def test_firebase_google_sign_in_rejects_bad_tokens_and_inactive_accounts(self):
        headers = {"X-CSRF-Token": self.csrf_token(self.student)}
        firebase_admin_app = object()
        with patch("app.firebase_admin.get_app", return_value=firebase_admin_app), patch(
            "app.firebase_auth.verify_id_token",
            side_effect=firebase_auth.InvalidIdTokenError("invalid token"),
        ):
            invalid = self.student.post(
                "/api/login/firebase",
                json={"idToken": "invalid-token"},
                headers=headers,
            )
        self.assertEqual(invalid.status_code, 401)

        with patch("app.firebase_admin.get_app", return_value=firebase_admin_app), patch(
            "app.firebase_auth.verify_id_token",
            side_effect=FirebaseError("unavailable", "Firebase is unavailable"),
        ):
            unavailable = self.student.post(
                "/api/login/firebase",
                json={"idToken": "firebase-id-token"},
                headers={"X-CSRF-Token": self.csrf_token(self.student)},
            )
        self.assertEqual(unavailable.status_code, 503)

        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE users SET active = 0 WHERE email = 'student@personal.example'")
        claims = {
            "email": "student@personal.example",
            "email_verified": True,
        }
        with patch("app.firebase_admin.get_app", return_value=firebase_admin_app), patch(
            "app.firebase_auth.verify_id_token",
            return_value=claims,
        ):
            inactive = self.student.post(
                "/api/login/firebase",
                json={"idToken": "firebase-id-token"},
                headers={"X-CSRF-Token": self.csrf_token(self.student)},
            )
        self.assertEqual(inactive.status_code, 403)

    def next_weekday(self):
        schedule_date = date.today() + timedelta(days=1)
        while schedule_date.weekday() >= 5:
            schedule_date += timedelta(days=1)
        return schedule_date.isoformat()

    def test_catalog_schedules_are_weekdays_and_repeat_without_duplicates(self):
        response = self.student.get("/api/schedules")
        self.assertEqual(response.status_code, 200)
        schedules = response.get_json()["schedules"]
        self.assertGreater(len(schedules), 300)
        self.assertEqual({item["service"] for item in schedules}, set(SERVICES))
        self.assertTrue(all(date.fromisoformat(item["date"]).weekday() < 5 for item in schedules))
        self.assertTrue(all(
            datetime.combine(date.fromisoformat(item["date"]), datetime.strptime(item["start"], "%H:%M").time())
            > datetime.now()
            for item in schedules
        ))

        with closing(sqlite3.connect(self.database)) as db:
            first_count = db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        self.student.get("/api/schedules")
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], first_count)

    def test_editing_generated_schedule_does_not_restore_old_template_values(self):
        schedules = self.student.get("/api/schedules").get_json()["schedules"]
        selected = schedules[0]
        staff = self.login_as("staff")
        token = self.csrf_token(staff)
        response = staff.put(
            f"/api/schedules/{selected['id']}",
            json={
                "service": selected["service"],
                "date": selected["date"],
                "start": selected["start"],
                "end": selected["end"],
                "capacity": selected["capacity"] - 1,
                "active": True,
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        updated = [
            item for item in self.student.get("/api/schedules").get_json()["schedules"]
            if item["service"] == selected["service"] and item["date"] == selected["date"]
            and item["start"] == selected["start"]
        ]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["capacity"], selected["capacity"] - 1)

    def test_overlapping_and_duplicate_bookings_are_rejected(self):
        staff = self.login_as("staff")
        token = self.csrf_token(staff)
        schedule_payload = {
            "service": "General Consultation",
            "date": self.next_weekday(),
            "start": "23:50",
            "end": "23:59",
            "capacity": 2,
        }
        created = staff.post("/api/schedules", json=schedule_payload, headers={"X-CSRF-Token": token})
        self.assertEqual(created.status_code, 201, created.get_json())
        duplicate_schedule = staff.post("/api/schedules", json=schedule_payload, headers={"X-CSRF-Token": token})
        self.assertEqual(duplicate_schedule.status_code, 409)

        schedule_id = created.get_json()["schedule"]["id"]
        booking = self.student.post(
            "/api/appointments",
            json={"scheduleId": schedule_id, "reason": "Consultation"},
            headers={"X-CSRF-Token": self.csrf_token(self.student)},
        )
        self.assertEqual(booking.status_code, 201, booking.get_json())
        duplicate_booking = self.student.post(
            "/api/appointments",
            json={"scheduleId": schedule_id, "reason": "Another consultation"},
            headers={"X-CSRF-Token": self.csrf_token(self.student)},
        )
        self.assertEqual(duplicate_booking.status_code, 409)

    def test_only_owner_can_cancel_pending_appointment(self):
        schedules = self.student.get("/api/schedules").get_json()["schedules"]
        booking = self.student.post(
            "/api/appointments",
            json={"scheduleId": schedules[0]["id"], "reason": "Consultation"},
            headers={"X-CSRF-Token": self.csrf_token(self.student)},
        )
        self.assertEqual(booking.status_code, 201, booking.get_json())
        appointment_id = booking.get_json()["appointment"]["dbId"]

        self.add_user("other-student", "Student")
        other_student = self.login_as("other-student")
        response = other_student.post(
            f"/api/appointments/{appointment_id}/action",
            json={"action": "cancel"},
            headers={"X-CSRF-Token": self.csrf_token(other_student)},
        )
        self.assertEqual(response.status_code, 403)

        response = self.student.post(
            f"/api/appointments/{appointment_id}/action",
            json={"action": "cancel"},
            headers={"X-CSRF-Token": self.csrf_token(self.student)},
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        with closing(sqlite3.connect(self.database)) as db:
            status = db.execute(
                "SELECT status FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()[0]
        self.assertEqual(status, "Cancelled")

        response = self.student.post(
            f"/api/appointments/{appointment_id}/action",
            json={"action": "cancel"},
            headers={"X-CSRF-Token": self.csrf_token(self.student)},
        )
        self.assertEqual(response.status_code, 403)

    def test_firebase_auth_is_enabled_and_legacy_calendar_tables_are_removed(self):
        rules = {rule.rule for rule in self.app.url_map.iter_rules()}
        self.assertIn("/api/auth/config", rules)
        self.assertIn("/api/login/firebase", rules)
        self.assertNotIn("/api/login/google", rules)
        for rule in self.app.url_map.iter_rules():
            self.assertNotIn("/api/google-calendar", rule.rule)

        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                """CREATE TABLE google_calendar_connections (
                       user_id INTEGER PRIMARY KEY,
                       access_token TEXT NOT NULL,
                       refresh_token TEXT NOT NULL
                   )"""
            )
            db.execute(
                """CREATE TABLE google_calendar_events (
                       appointment_id INTEGER PRIMARY KEY,
                       google_event_id TEXT NOT NULL
                   )"""
            )

        create_app({
            "TESTING": True,
            "DATABASE": str(self.database),
            "SECRET_KEY": "test-secret-key",
        })

        with closing(sqlite3.connect(self.database)) as db:
            calendar_tables = db.execute(
                """SELECT name FROM sqlite_master
                   WHERE type = 'table' AND name LIKE 'google_calendar_%'"""
            ).fetchall()
        self.assertEqual(calendar_tables, [])

    def test_personnel_can_see_completed_visits_for_today(self):
        schedules = self.student.get("/api/schedules").get_json()["schedules"]
        today = date.today().isoformat()
        with closing(sqlite3.connect(self.database)) as db, db:
            schedule_id = db.execute(
                "SELECT id FROM schedules WHERE date = ? ORDER BY start_time LIMIT 1",
                (today,),
            ).fetchone()
            if schedule_id is None:
                self.skipTest("No generated schedule exists for today.")
            appointment_id = db.execute(
                """INSERT INTO appointments (reference, user_id, schedule_id, reason, status, created_at)
                   VALUES ('CC-TEST-COMPLETE', 1, ?, 'Completed visit', 'Completed', ?)""",
                (schedule_id[0], datetime.now().isoformat()),
            ).lastrowid

        personnel = self.login_as("personnel")
        appointments = personnel.get("/api/appointments").get_json()["appointments"]
        self.assertIn(appointment_id, [item["dbId"] for item in appointments])
        self.assertEqual(
            next(item for item in appointments if item["dbId"] == appointment_id)["status"],
            "Completed",
        )

    def test_past_appointment_is_not_counted_as_upcoming(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            schedule_id = db.execute(
                """INSERT INTO schedules (service, date, start_time, end_time, capacity, active)
                   VALUES ('General Consultation', ?, '00:01', '00:30', 1, 1)""",
                (date.today().isoformat(),),
            ).lastrowid
            db.execute(
                """INSERT INTO appointments (reference, user_id, schedule_id, reason, status, created_at)
                   VALUES ('CC-TEST-PAST', 1, ?, 'Earlier appointment', 'Approved', ?)""",
                (schedule_id, datetime.now().isoformat()),
            )

        counts = self.student.get("/api/dashboard").get_json()["counts"]
        self.assertEqual(counts["upcoming"], 0)
        self.assertEqual(counts["approved"], 1)

    def test_last_active_administrator_cannot_be_deactivated(self):
        admin = self.login_as("admin")
        token = self.csrf_token(admin)
        with closing(sqlite3.connect(self.database)) as db:
            admin_id = db.execute(
                "SELECT id FROM users WHERE email = 'admin@example.edu'"
            ).fetchone()[0]
        response = admin.patch(
            f"/api/users/{admin_id}",
            json={"role": "Administrator", "active": False},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
