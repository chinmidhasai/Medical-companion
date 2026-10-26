# MediCompanion — AI-Assisted Medical Decision Support Prototype

A student capstone prototype combining private patient accounts, caregiver access, prescription uploads, manually verified medicine schedules, browser reminders, a simple educational knowledge-base agent, and nearby healthcare facility search using OpenStreetMap data.

## Important limitations

- This is an educational prototype, not a medical device and not suitable for real clinical decisions.
- It does not diagnose, prescribe, recommend dose changes, or reliably identify a tablet from its image.
- Prescription details must be checked manually against a current prescription by the patient/authorized person.
- The agent uses simple keyword-based rules, not a validated medical AI model. It can use a patient's saved profile and active medicine list as context, but cannot read uploaded prescription images/PDFs or check remedy/medicine interactions. Its mild-symptom suggestions are general comfort measures, not proven cures or a substitute for professional advice; it does not recommend medicines. Ask a pharmacist or clinician before trying herbs or supplements.
- Browser reminders run while the dashboard page is open. They are not guaranteed when the browser is closed or the device restricts background activity.
- Caregiver pending reminders are displayed on dashboard load; actual push/SMS/email alerts require integration with a notification provider and deployment configuration.
- Hospital search uses public OpenStreetMap/Overpass data, which may be incomplete or unavailable. Verify phone numbers, opening hours, emergency services, and suitability directly.
- Do not upload real patient records to a public demo. Before deployment, add CSRF protection, rate limiting, secure cookies, production-grade secrets, encrypted storage/backups, HTTPS, logging, privacy/consent workflows, and security testing.

## Features included

1. Separate patient and caregiver accounts with hashed passwords.
2. Patient medical profile and caregiver linking by registered email.
3. Prescription photo/PDF upload.
4. Medicine name, prescribed dose, frequency, times, optional photo, dates, and instructions.
5. Daily schedule records with Taken, Snooze, and Missed status.
6. Browser notification checks while the patient dashboard remains open.
7. Caregiver view of linked patient's profile, schedule, and pending reminder records.
8. Simple rule-based educational agent that asks about symptom severity, recommends professional care for severe symptoms, offers cautious non-medicine comfort measures for mild symptoms, and handles emergency warning signs.
9. Nearby hospital/clinic search using device location or manually entered coordinates.

## Run locally

Use Python 3.10 or newer.

### Windows

1. Extract the ZIP.
2. Open Command Prompt or VS Code terminal in the `medical_companion_capstone` folder.
3. Create a virtual environment:

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   ```

4. Install dependencies:

   ```bat
   pip install -r requirements.txt
   ```

5. Optional: copy `.env.example` to `.env` and set a strong `FLASK_SECRET_KEY`. For this starter, environment variables must be set in your terminal or loaded with an additional dotenv package; see below.
6. Start the application:

   ```bat
   python app.py
   ```

7. Open `http://127.0.0.1:5000` in your browser.

### Set a secret key in Windows Command Prompt

```bat
set FLASK_SECRET_KEY=use-a-long-random-secret-here
python app.py
```

In PowerShell:

```powershell
$env:FLASK_SECRET_KEY="use-a-long-random-secret-here"
python app.py
```

The SQLite database is created automatically at `data/medical_companion.db`. Uploaded files are stored outside the public static directory in `data/uploads/` and served through an authenticated route.

## Suggested 5-day implementation plan

### Day 1 — Accounts and privacy boundaries
- Register as a patient and as a caregiver using two separate browser sessions.
- Verify sign-in/sign-out and patient profile.
- Link caregiver by the caregiver account's registered email.
- Confirm one patient cannot access another patient's records by changing URLs.

### Day 2 — Prescription and medicine management
- Upload a test prescription image/PDF.
- Add medicine details manually and attach a sample image.
- Edit and archive a medicine.
- Verify times use 24-hour format and reflect the doctor's written instructions.

### Day 3 — Reminders and caregiver view
- Add a test medicine scheduled a few minutes ahead.
- Keep the patient dashboard open and allow browser notifications.
- Test Taken, Snooze, and Missed.
- Open caregiver dashboard and verify linked patient schedule/pending statuses.

### Day 4 — Knowledge-base agent and hospital finder
- Test general questions about diabetes, cold, cough, fever, and prescription organization.
- Test emergency-warning text such as “difficulty breathing”.
- Test hospital search with location permission and manual coordinates.
- Verify results directly; map data can be incomplete.

### Day 5 — QA, documentation, and presentation
- Test empty fields, invalid time, unsupported file type, large file, and unauthorized access.
- Use only fictional/sample patient data for the demo.
- Prepare architecture, ER diagram, screenshots, test cases, limitations, and future scope.
- Do not claim that browser reminders are guaranteed in the background or that the agent diagnoses conditions.

## Demo test sequence

1. Create patient account.
2. Create caregiver account in another browser/private window.
3. Link caregiver email from patient profile.
4. Upload a sample prescription.
5. Add a sample medicine and times (use fictional test data).
6. Open patient dashboard and test reminder actions.
7. Open caregiver dashboard and view patient schedule.
8. Ask agent a general health information question.
9. Open hospital finder and test nearby search.
10. Sign out and verify protected pages redirect to sign-in.

## Suggested next improvements

- OCR extraction with manual confirmation screen.
- Email/SMS/push notifications for caregiver alerts.
- Android app or service-worker/PWA architecture for improved notification experience.
- CSRF protection, email verification, password reset, rate limiting, and audit logging.
- Database migrations, automated tests, backups, and production deployment.
- Curated, cited medical knowledge from trusted clinical sources with review dates.
- Hospital data provider that supports verified opening hours and emergency services.
