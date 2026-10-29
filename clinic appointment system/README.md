# Campus Clinic

Campus Clinic is a Flask application with a SQLite database, server-side sessions, and role-protected appointment workflows.

## Run locally on Windows

From the project folder in PowerShell, configure and trust a localhost development certificate once:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-https.ps1
```

Then start Campus Clinic with:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

The launcher creates the Python virtual environment and installs dependencies on its first run. Keep the PowerShell window open. Browse to **https://localhost:3000/**. The one-time setup adds a local development certificate authority to the current Windows user's trust store so the browser can validate the localhost certificate. The certificate files are stored under the ignored `instance` folder and are not committed.

If you need to use HTTP temporarily, start the server with `powershell -ExecutionPolicy Bypass -File .\run-local.ps1 -Http` and open `http://localhost:3000/`. HTTP does not encrypt traffic and disables Secure cookies; prefer HTTPS.

Create the initial administrator once, using a second PowerShell window in the project folder:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-admin
```

The command prompts for the initial administrator's name, email address, employee ID, and password. Usernames are generated internally; sign in with the email address. The password is entered without being echoed and must contain at least 8 characters, including a number and a symbol. It refuses to create a second initial administrator. If you already created an administrator, skip this step.

If an existing account's password needs to be restored, run this command on the trusted computer hosting the app:

```powershell
.\.venv\Scripts\python.exe -m flask --app app reset-password
```

Enter the account's email address and the new password twice when prompted. The password is not echoed, is stored as a secure hash, and must meet the same requirements as registration. This resets only an active existing account; it does not create accounts or reactivate inactive ones.

The SQLite database is created at `instance/campus_clinic.sqlite3`. All six offered services are visible to users. Default weekday schedules repeat Monday through Friday and are generated for the next 90 days, with the schedule continuing to roll forward:

| Service | Time | Slots per weekday |
| --- | --- | ---: |
| General Consultation | 8:00 AM–12:00 PM | 10 |
| Basic Health Screening | 8:00 AM–12:00 PM | 20 |
| Dental Cleaning | 1:00 PM–5:00 PM | 20 |
| Dental Consultation and Checkup | 1:00 PM–5:00 PM | 10 |
| Tooth Extraction (bunot) | 3:00 PM–5:00 PM | 10 |
| Medical Certificate / Health Assessment Request | 10:00 AM–12:00 PM | 10 |

The number of remaining slots updates as appointments are requested. Clinic Staff or Administrators can still add dated schedules from **Clinic Schedules**. An administrator can assign the Clinic Staff role under **User Management**. Public registration only permits Student and Faculty accounts.

Existing schedules for services no longer offered are deactivated at startup; existing appointment records are retained.

Clinic Personnel can check in today's approved appointments and complete visits. Completed visits remain visible in the personnel appointment queue for the rest of the day. Past time slots are not offered or bookable, and a user cannot submit duplicate active requests for the same schedule.

## Firebase Google sign-in

The login page offers **Continue with Google** when Firebase is configured. Sign-in requires an existing active clinic account with the same verified email address; Firebase sign-in does not register users or assign clinic roles. Email-and-password sign-in remains available.

1. In Firebase Console, create a Firebase project and register a Web app. Under **Authentication → Sign-in method**, enable Google. Add `localhost` and your deployed app's host under **Authentication → Settings → Authorized domains**.
2. Copy the Web app's API key, Auth domain, Project ID, and App ID into a project-root `.env.local` file using the variable names in [.env.local.example](./.env.local.example). This file is ignored by Git.
3. Configure Firebase Admin credentials for the Flask server. For local development, create a service-account key in Firebase project settings and set `GOOGLE_APPLICATION_CREDENTIALS` to its path in `.env.local`. Keep the JSON key outside the repository and never commit or share it. A production server can use Application Default Credentials instead.
4. Restart the Flask app after changing environment variables. Google sign-in uses Firebase's browser SDK and sends the Firebase ID token to the Flask API; the server verifies the token and checks the existing clinic account before creating a session.

## Firebase Hosting

The Firebase Hosting configuration serves a generated static copy of the frontend from `public/`; this build output is ignored by Git. Before deploying frontend changes, run `npm run build`, then `firebase deploy --only hosting`. The build embeds only the Firebase Web app configuration from `.env.local` (or the matching `FIREBASE_*` build environment variables) so the Google sign-in button can appear on the static page. These Web app values are public client configuration, not Admin credentials. Static Hosting does not run this Flask application's Python backend, so account sign-in, Google-token verification, appointments, and other `/api` features will not work until the backend is deployed separately and connected through Firebase Hosting rewrites. Keep using the Flask server locally, or deploy the backend separately and configure Hosting rewrites before using Hosting as the full application.

## Account access

- The first administrator is created through `flask --app app create-admin`, never through public registration.
- Administrators can create Clinic Staff, Clinic Personnel, and additional Administrator accounts in **User Management**, or assign roles to existing accounts there. Public registration only permits Student and Faculty accounts.
- Clinic Staff can create schedules and review pending appointments. Rejection requires a reason.
- Clinic Personnel can check in and complete today's approved visits.
- Students and Faculty can book and view only their own appointments.
- An administrator cannot accidentally deactivate or demote the last active administrator.

## Security configuration

Set `CAMPUS_CLINIC_SECRET_KEY` to a long, random, private value and keep it stable across restarts and application workers. Do not commit it to source control. The HTTPS launcher sets `CAMPUS_CLINIC_COOKIE_SECURE=1`. Use a production WSGI server and a certificate from a trusted public certificate authority for deployment; the local development certificate and Flask server are for local use only.

Passwords must contain at least 8 characters, including a number and a symbol, and are stored as Werkzeug password hashes, not plaintext. Mutating API requests require a session CSRF token. Sessions use HttpOnly and SameSite=Lax cookies. Email-and-password sign-in is rate-limited after repeated failed attempts. The application does not send email verification or password-reset messages.

## Tests

Run the backend regression suite from the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
