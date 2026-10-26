import os
import json
import sqlite3
from datetime import datetime, date
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, g, jsonify, abort, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

APP_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "medical_companion.db")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY", "dev-only-change-this-before-deployment"
)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('patient','caregiver')),
        caregiver_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(caregiver_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS prescriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        original_filename TEXT NOT NULL,
        stored_filename TEXT NOT NULL,
        notes TEXT DEFAULT '',
        uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS medicines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        dose TEXT NOT NULL,
        frequency TEXT NOT NULL DEFAULT 'Daily',
        times_json TEXT NOT NULL DEFAULT '[]',
        photo_filename TEXT DEFAULT '',
        start_date TEXT DEFAULT '',
        end_date TEXT DEFAULT '',
        instructions TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS medical_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        conditions TEXT DEFAULT '',
        allergies TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS dose_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        medicine_id INTEGER NOT NULL,
        scheduled_date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('pending','taken','snoozed','missed')),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(medicine_id, scheduled_date, scheduled_time),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(medicine_id) REFERENCES medicines(id) ON DELETE CASCADE
    );
    """)
    db.commit()
    db.close()

init_db()

@app.template_filter("from_json")
def from_json_filter(value):
    try:
        return json.loads(value or "[]")
    except (ValueError, TypeError):
        return []

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

@app.context_processor
def inject_user():
    return {"current_user": current_user(), "today": date.today().isoformat()}

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def patient_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "patient":
            abort(403)
        return view(*args, **kwargs)
    return wrapped

def linked_patient_ids(caregiver_id):
    rows = get_db().execute(
        "SELECT id FROM users WHERE caregiver_id=? AND role='patient'",
        (caregiver_id,)
    ).fetchall()
    return [r["id"] for r in rows]

def save_upload(file_storage, prefix):
    if not file_storage or not file_storage.filename:
        return None, None
    if not allowed_file(file_storage.filename):
        raise ValueError("File type not supported. Use PNG, JPG, WEBP, or PDF.")
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[1].lower()
    stored = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.{ext}"
    file_storage.save(os.path.join(UPLOAD_DIR, stored))
    return original, stored

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "patient")
        if not name or not email or len(password) < 8 or role not in ("patient", "caregiver"):
            flash("Enter your name, a valid email, a role, and a password of at least 8 characters.", "danger")
            return render_template("register.html")
        db = get_db()
        try:
            db.execute(
                "INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                (name, email, generate_password_hash(password), role)
            )
            db.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("index"))


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    """Serve private uploads only to the owning patient or their linked caregiver."""
    user = current_user()
    db = get_db()
    # Only allow a filename that is referenced by a record; do not expose arbitrary files.
    prescription = db.execute(
        "SELECT user_id FROM prescriptions WHERE stored_filename=?", (filename,)
    ).fetchone()
    medicine = db.execute(
        "SELECT user_id FROM medicines WHERE photo_filename=?", (filename,)
    ).fetchone()
    owner_ids = set()
    if prescription:
        owner_ids.add(prescription["user_id"])
    if medicine:
        owner_ids.add(medicine["user_id"])
    allowed = user["id"] in owner_ids
    if not allowed and user["role"] == "caregiver":
        allowed = any(pid in owner_ids for pid in linked_patient_ids(user["id"]))
    if not allowed:
        abort(403)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    db = get_db()
    if user["role"] == "patient":
        meds = db.execute(
            "SELECT * FROM medicines WHERE user_id=? AND active=1 ORDER BY name",
            (user["id"],)
        ).fetchall()
        records = db.execute(
            "SELECT * FROM prescriptions WHERE user_id=? ORDER BY uploaded_at DESC",
            (user["id"],)
        ).fetchall()
        info = db.execute("SELECT * FROM medical_info WHERE user_id=?", (user["id"],)).fetchone()
        logs = db.execute(
            """SELECT dl.*, m.name, m.dose FROM dose_logs dl
               JOIN medicines m ON m.id=dl.medicine_id
               WHERE dl.user_id=? AND dl.scheduled_date=?
               ORDER BY dl.scheduled_time""",
            (user["id"], date.today().isoformat())
        ).fetchall()
        return render_template("patient_dashboard.html", meds=meds, records=records, info=info, logs=logs)
    ids = linked_patient_ids(user["id"])
    patients = []
    for pid in ids:
        p = db.execute("SELECT id,name,email FROM users WHERE id=?", (pid,)).fetchone()
        pmeds = db.execute(
            "SELECT * FROM medicines WHERE user_id=? AND active=1 ORDER BY name", (pid,)
        ).fetchall()
        plogs = db.execute(
            """SELECT dl.*, m.name, m.dose FROM dose_logs dl
               JOIN medicines m ON m.id=dl.medicine_id
               WHERE dl.user_id=? AND dl.scheduled_date=? AND dl.status='pending'
               ORDER BY dl.scheduled_time""",
            (pid, date.today().isoformat())
        ).fetchall()
        patients.append({"user": p, "medicines": pmeds, "pending": plogs})
    return render_template("caregiver_dashboard.html", patients=patients)

@app.route("/profile", methods=["GET", "POST"])
@patient_required
def profile():
    user = current_user()
    db = get_db()
    if request.method == "POST":
        conditions = request.form.get("conditions", "").strip()
        allergies = request.form.get("allergies", "").strip()
        notes = request.form.get("notes", "").strip()
        caregiver_email = request.form.get("caregiver_email", "").strip().lower()
        caregiver_id = None
        if caregiver_email:
            caregiver = db.execute(
                "SELECT id FROM users WHERE email=? AND role='caregiver'", (caregiver_email,)
            ).fetchone()
            if not caregiver:
                flash("No caregiver account found for that email. Ask them to register first.", "danger")
                return redirect(url_for("profile"))
            caregiver_id = caregiver["id"]
        db.execute(
            """INSERT INTO medical_info(user_id,conditions,allergies,notes)
               VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
               conditions=excluded.conditions, allergies=excluded.allergies, notes=excluded.notes""",
            (user["id"], conditions, allergies, notes)
        )
        db.execute("UPDATE users SET caregiver_id=? WHERE id=?", (caregiver_id, user["id"]))
        db.commit()
        flash("Profile and caregiver access updated.", "success")
        return redirect(url_for("profile"))
    info = db.execute("SELECT * FROM medical_info WHERE user_id=?", (user["id"],)).fetchone()
    caregiver = None
    if user["caregiver_id"]:
        caregiver = db.execute("SELECT name,email FROM users WHERE id=?", (user["caregiver_id"],)).fetchone()
    return render_template("profile.html", info=info, caregiver=caregiver)

@app.route("/prescriptions", methods=["GET", "POST"])
@patient_required
def prescriptions():
    user = current_user()
    db = get_db()
    if request.method == "POST":
        file = request.files.get("prescription")
        notes = request.form.get("notes", "").strip()
        try:
            original, stored = save_upload(file, f"rx_user{user['id']}")
            if not stored:
                flash("Choose a prescription image or PDF first.", "danger")
                return redirect(url_for("prescriptions"))
            db.execute(
                "INSERT INTO prescriptions(user_id,original_filename,stored_filename,notes) VALUES(?,?,?,?)",
                (user["id"], original, stored, notes)
            )
            db.commit()
            flash("Prescription uploaded. Review the original and enter medicine details manually; OCR may be added later.", "success")
            return redirect(url_for("prescriptions"))
        except ValueError as exc:
            flash(str(exc), "danger")
    rows = db.execute(
        "SELECT * FROM prescriptions WHERE user_id=? ORDER BY uploaded_at DESC", (user["id"],)
    ).fetchall()
    return render_template("prescriptions.html", prescriptions=rows)

@app.route("/medicines")
@patient_required
def medicines():
    rows = get_db().execute(
        "SELECT * FROM medicines WHERE user_id=? ORDER BY active DESC, name",
        (current_user()["id"],)
    ).fetchall()
    return render_template("medicines.html", medicines=rows)

@app.route("/medicines/add", methods=["GET", "POST"])
@patient_required
def add_medicine():
    user = current_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        dose = request.form.get("dose", "").strip()
        frequency = request.form.get("frequency", "Daily").strip()
        times = sorted(set(t.strip() for t in request.form.get("times", "").split(",") if t.strip()))
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        instructions = request.form.get("instructions", "").strip()
        if not name or not dose or not times:
            flash("Medicine name, prescribed dose, and at least one time are required.", "danger")
            return render_template("medicine_form.html", medicine=None)
        for t in times:
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                flash(f"Invalid time: {t}. Use 24-hour format such as 08:00, 20:30.", "danger")
                return render_template("medicine_form.html", medicine=None)
        photo = request.files.get("photo")
        try:
            _, stored_photo = save_upload(photo, f"med_user{user['id']}")
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("medicine_form.html", medicine=None)
        db = get_db()
        cur = db.execute(
            """INSERT INTO medicines(user_id,name,dose,frequency,times_json,photo_filename,
               start_date,end_date,instructions) VALUES(?,?,?,?,?,?,?,?,?)""",
            (user["id"], name, dose, frequency, json.dumps(times), stored_photo or "",
             start_date, end_date, instructions)
        )
        db.commit()
        flash("Medicine added. Check the prescription and schedule carefully.", "success")
        return redirect(url_for("medicines"))
    return render_template("medicine_form.html", medicine=None)

@app.route("/medicines/<int:medicine_id>/edit", methods=["GET", "POST"])
@patient_required
def edit_medicine(medicine_id):
    user = current_user()
    db = get_db()
    med = db.execute(
        "SELECT * FROM medicines WHERE id=? AND user_id=?", (medicine_id, user["id"])
    ).fetchone()
    if not med:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        dose = request.form.get("dose", "").strip()
        times = sorted(set(t.strip() for t in request.form.get("times", "").split(",") if t.strip()))
        for t in times:
            try: datetime.strptime(t, "%H:%M")
            except ValueError:
                flash("Use valid 24-hour times, e.g. 08:00, 20:30.", "danger")
                return render_template("medicine_form.html", medicine=med)
        if not name or not dose or not times:
            flash("Medicine name, dose, and at least one time are required.", "danger")
            return render_template("medicine_form.html", medicine=med)
        photo = request.files.get("photo")
        try:
            _, stored_photo = save_upload(photo, f"med_user{user['id']}")
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("medicine_form.html", medicine=med)
        db.execute(
            """UPDATE medicines SET name=?,dose=?,frequency=?,times_json=?,photo_filename=COALESCE(NULLIF(?,''),photo_filename),
               start_date=?,end_date=?,instructions=? WHERE id=? AND user_id=?""",
            (name, dose, request.form.get("frequency", "Daily"), json.dumps(times),
             stored_photo or "", request.form.get("start_date", ""), request.form.get("end_date", ""),
             request.form.get("instructions", "").strip(), medicine_id, user["id"])
        )
        db.commit()
        flash("Medicine details updated.", "success")
        return redirect(url_for("medicines"))
    return render_template("medicine_form.html", medicine=med)

@app.route("/medicines/<int:medicine_id>/archive", methods=["POST"])
@patient_required
def archive_medicine(medicine_id):
    db = get_db()
    db.execute("UPDATE medicines SET active=0 WHERE id=? AND user_id=?",
               (medicine_id, current_user()["id"]))
    db.commit()
    flash("Medicine archived; future reminders are disabled.", "info")
    return redirect(url_for("medicines"))

def ensure_today_logs(user_id):
    db = get_db()
    today_str = date.today().isoformat()
    meds = db.execute(
        "SELECT id,times_json,start_date,end_date FROM medicines WHERE user_id=? AND active=1",
        (user_id,)
    ).fetchall()
    for med in meds:
        if med["start_date"] and med["start_date"] > today_str:
            continue
        if med["end_date"] and med["end_date"] < today_str:
            continue
        try:
            times = json.loads(med["times_json"])
        except Exception:
            times = []
        for t in times:
            db.execute(
                """INSERT OR IGNORE INTO dose_logs(user_id,medicine_id,scheduled_date,scheduled_time,status)
                   VALUES(?,?,?,?, 'pending')""",
                (user_id, med["id"], today_str, t)
            )
    db.commit()

@app.route("/api/today")
@login_required
def api_today():
    user = current_user()
    if user["role"] != "patient":
        return jsonify({"error": "Patient account required"}), 403
    ensure_today_logs(user["id"])
    rows = get_db().execute(
        """SELECT dl.id,dl.scheduled_date,dl.scheduled_time,dl.status,
                  m.id AS medicine_id,m.name,m.dose,m.photo_filename,m.instructions
           FROM dose_logs dl JOIN medicines m ON m.id=dl.medicine_id
           WHERE dl.user_id=? AND dl.scheduled_date=? AND m.active=1
           ORDER BY dl.scheduled_time""",
        (user["id"], date.today().isoformat())
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/log/<int:log_id>", methods=["POST"])
@patient_required
def update_log(log_id):
    status = request.json.get("status") if request.is_json else request.form.get("status")
    if status not in ("taken", "snoozed", "missed", "pending"):
        return jsonify({"error": "Invalid status"}), 400
    db = get_db()
    row = db.execute("SELECT * FROM dose_logs WHERE id=? AND user_id=?",
                     (log_id, current_user()["id"])).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    db.execute("UPDATE dose_logs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (status, log_id))
    db.commit()
    return jsonify({"ok": True, "status": status})

@app.route("/agent", methods=["GET", "POST"])
@login_required
def agent():
    answer = None
    question = ""
    awaiting_severity = False
    if request.method == "POST":
        severity = request.form.get("severity", "")
        pending_question = session.get("pending_health_question", "")
        if severity in ("severe", "mild") and pending_question:
            question = pending_question
            answer = medical_agent_answer(question, current_user(), severity)
            session.pop("pending_health_question", None)
        else:
            question = request.form.get("question", "").strip()
            session.pop("pending_health_question", None)
            answer = medical_agent_answer(question, current_user())
            if has_symptom_concern(question) and not is_emergency_concern(question):
                session["pending_health_question"] = question
                awaiting_severity = True
    return render_template(
        "agent.html", answer=answer, question=question,
        awaiting_severity=awaiting_severity
    )

SYMPTOM_TERMS = (
    "cold", "cough", "itch", "rash", "neck pain", "sore throat",
    "runny nose", "congestion", "sneeze", "fever", "headache",
    "stomach pain", "nausea", "dizzy", "swelling", "pain", "hurts",
)
EMERGENCY_TERMS = (
    "can't breathe", "cannot breathe", "difficulty breathing",
    "severe chest pain", "unconscious", "stroke", "blue lips",
    "swelling of the face", "swelling of the throat", "throat closing",
    "stiff neck and fever", "fever and stiff neck", "sudden weakness",
)

def has_symptom_concern(question):
    q = question.lower()
    return any(term in q for term in SYMPTOM_TERMS)

def is_emergency_concern(question):
    q = question.lower()
    return any(term in q for term in EMERGENCY_TERMS)

def agent_health_context(user):
    if not user or user["role"] != "patient":
        return {"medicine_count": 0, "has_profile_details": False}

    db = get_db()
    medicine_count = db.execute(
        "SELECT COUNT(*) FROM medicines WHERE user_id=? AND active=1",
        (user["id"],)
    ).fetchone()[0]
    info = db.execute(
        "SELECT conditions, allergies, notes FROM medical_info WHERE user_id=?",
        (user["id"],)
    ).fetchone()
    has_profile_details = bool(
        info and any((info[field] or "").strip() for field in ("conditions", "allergies", "notes"))
    )
    return {
        "medicine_count": medicine_count,
        "has_profile_details": has_profile_details,
    }

def medical_agent_answer(question, user, severity=None):
    q = question.lower()
    health_context = agent_health_context(user)
    # Educational knowledge base only; not diagnosis or personalized treatment.
    if is_emergency_concern(question):
        return ("This may be an emergency. Call your local emergency number or go to the nearest "
                "emergency department now. Do not wait for this app to assess your symptoms.")
    if has_symptom_concern(question):
        if severity == "severe":
            return ("Because you describe these symptoms as severe, contact a healthcare professional "
                    "or seek urgent medical care now. If you have trouble breathing, chest pain, "
                    "fainting, confusion, face or throat swelling, or sudden weakness, call your "
                    "local emergency number. I cannot assess severity or diagnose you.")
        if severity == "mild":
            if "itch" in q or "rash" in q:
                care = ("For mild itching, try a cool compress, avoid scratching and scented products, "
                        "and use a simple fragrance-free moisturizer. Seek medical advice if it spreads, "
                        "persists, worsens, or comes with other symptoms.")
            elif "neck pain" in q or "neck" in q:
                care = ("For mild neck discomfort, try a warm or cool compress and gentle, comfortable "
                        "movement; avoid forcing stretches. Seek medical advice if it worsens or does "
                        "not improve.")
            elif "cough" in q:
                care = "For a mild cough, rest, drink fluids, and consider humidified air."
                if not health_context["medicine_count"] and not health_context["has_profile_details"]:
                    care += (" Honey may soothe a cough for people over 1 year old; never give honey "
                             "to an infant.")
            elif "cold" in q or "runny nose" in q or "congestion" in q or "sneeze" in q:
                care = ("For mild cold symptoms, rest, drink fluids, and consider humidified air or a "
                        "saline nasal rinse/spray. Use safe, clean water for any nasal rinse.")
            else:
                care = ("For mild symptoms, rest, drink fluids, and avoid anything that seems to "
                        "worsen them. Monitor how you feel and seek medical advice if symptoms worsen "
                        "or do not improve.")
            personal_caution = ""
            if health_context["medicine_count"] or health_context["has_profile_details"]:
                context_details = []
                if health_context["medicine_count"]:
                    context_details.append(
                        f"{health_context['medicine_count']} active medicine(s) are recorded"
                    )
                if health_context["has_profile_details"]:
                    context_details.append("health details are saved in your profile")
                personal_caution = (
                    " I can see that " + " and ".join(context_details) +
                    ", but I cannot determine whether a remedy is safe with your "
                    "medicines, conditions, or allergies. Check with a pharmacist or clinician "
                    "before trying herbs, supplements, or ingested remedies; do not stop or change "
                    "prescribed treatment."
                )
            return (care + " These are comfort measures, not a cure or diagnosis. This assistant "
                    "does not recommend medicines." + personal_caution +
                    " Contact a healthcare professional if you are pregnant, have a significant "
                    "health condition, or are worried.")
        return ("How severe are your symptoms: mild/normal or severe? Choose one below. "
                "If you have trouble breathing, severe chest pain, fainting, confusion, face or throat "
                "swelling, or sudden weakness, seek emergency help now rather than waiting for a reply.")

    kb = {
        "diabetes": "Diabetes is a condition involving elevated blood glucose. Follow your clinician's care plan and do not change medicines based on this general information.",
        "cold": "A common cold is usually a mild viral respiratory illness. Rest and fluids may help. Seek professional advice if symptoms worsen or you have risk factors.",
        "cough": "Cough can have many causes. Seek medical advice for persistent or worsening symptoms, and urgent care for difficulty breathing, blue lips, severe chest pain, or confusion.",
        "fever": "Fever can have many causes. Monitor symptoms and seek medical advice if it persists or worsens. Seek urgent care for severe symptoms, confusion, breathing difficulty, or other emergency warning signs.",
        "medicine": "Use medicines only as prescribed by your licensed healthcare professional. Do not start, stop, or change a dose based on this assistant.",
        "prescription": "Upload your prescription under Prescriptions, then manually verify medicine name, dose, and timing before saving the schedule."
    }
    matched = [text for key, text in kb.items() if key in q]
    if matched:
        return " ".join(matched) + "\n\nSafety note: I cannot diagnose, prescribe, or determine the right treatment. Contact a qualified healthcare professional for personal medical advice."
    return ("I can help with general educational information about diabetes, colds, coughs, fever, and prescription organization. "
            "Please describe your question in general terms. I cannot diagnose or recommend medication changes.")

@app.route("/hospitals")
@login_required
def hospitals():
    return render_template("hospitals.html")

@app.route("/api/hospitals")
@login_required
def api_hospitals():
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
        radius = min(max(int(request.args.get("radius", "5000")), 500), 20000)
    except ValueError:
        return jsonify({"error": "Provide valid latitude and longitude."}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Coordinates are outside valid ranges."}), 400

    # OpenStreetMap Overpass: public map data can be incomplete or temporarily unavailable.
    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"~"hospital|clinic|doctors"](around:{radius},{lat},{lon});
      way["amenity"~"hospital|clinic|doctors"](around:{radius},{lat},{lon});
      relation["amenity"~"hospital|clinic|doctors"](around:{radius},{lat},{lon});
    );
    out center tags;
    """
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            timeout=20,
            headers={"User-Agent": "MedicalCompanionStudentPrototype/1.0"}
        )
        resp.raise_for_status()
        payload = resp.json()
        results = []
        for el in payload.get("elements", []):
            tags = el.get("tags", {})
            name = tags.get("name")
            if not name:
                continue
            elat = el.get("lat", el.get("center", {}).get("lat"))
            elon = el.get("lon", el.get("center", {}).get("lon"))
            if elat is None or elon is None:
                continue
            results.append({
                "name": name,
                "type": tags.get("amenity", "healthcare facility"),
                "lat": elat,
                "lon": elon,
                "address": ", ".join(filter(None, [
                    tags.get("addr:street"), tags.get("addr:city"), tags.get("addr:postcode")
                ])) or "Address not available in map data",
                "phone": tags.get("phone") or tags.get("contact:phone") or "Phone not listed",
                "emergency": tags.get("emergency", "Not verified"),
                "maps_url": f"https://www.openstreetmap.org/?mlat={elat}&mlon={elon}#map=17/{elat}/{elon}"
            })
        return jsonify({"source": "OpenStreetMap contributors", "results": results})
    except Exception:
        return jsonify({
            "error": "Hospital search is temporarily unavailable. Try again or open a trusted maps app.",
            "results": []
        }), 503

@app.route("/caregiver/patient/<int:patient_id>")
@login_required
def caregiver_patient(patient_id):
    user = current_user()
    if user["role"] != "caregiver" or patient_id not in linked_patient_ids(user["id"]):
        abort(403)
    db = get_db()
    patient = db.execute("SELECT id,name,email FROM users WHERE id=?", (patient_id,)).fetchone()
    meds = db.execute("SELECT * FROM medicines WHERE user_id=? AND active=1 ORDER BY name", (patient_id,)).fetchall()
    info = db.execute("SELECT * FROM medical_info WHERE user_id=?", (patient_id,)).fetchone()
    ensure_today_logs(patient_id)
    logs = db.execute(
        """SELECT dl.*,m.name,m.dose FROM dose_logs dl JOIN medicines m ON m.id=dl.medicine_id
           WHERE dl.user_id=? AND dl.scheduled_date=? ORDER BY dl.scheduled_time""",
        (patient_id, date.today().isoformat())
    ).fetchall()
    return render_template("caregiver_patient.html", patient=patient, medicines=meds, info=info, logs=logs)

@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message="You do not have permission to access this information."), 403

@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, message="The requested page could not be found."), 404

@app.errorhandler(413)
def too_large(error):
    return render_template("error.html", code=413, message="Upload too large. Maximum file size is 8 MB."), 413

if __name__ == "__main__":
    # Development server only. Do not expose this directly to the public internet.
    app.run(debug=True)
