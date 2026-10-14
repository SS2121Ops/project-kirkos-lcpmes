import os
from datetime import datetime, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "እባክዎ መጀመሪያ ይግቡ።"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="Staff")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class WorkProcess(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    teams = db.relationship("Team", backref="process", cascade="all, delete-orphan")
    plans = db.relationship("Plan", backref="process")


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    process_id = db.Column(db.Integer, db.ForeignKey("work_process.id"), nullable=False)
    plans = db.relationship("Plan", backref="team")


class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fiscal_year = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    objective = db.Column(db.Text)
    process_id = db.Column(db.Integer, db.ForeignKey("work_process.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(30), nullable=False, default="Draft")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    performances = db.relationship("Performance", backref="plan", cascade="all, delete-orphan")


class KPI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    unit = db.Column(db.String(50), default="%")
    target_value = db.Column(db.Float, nullable=False, default=0)
    process_id = db.Column(db.Integer, db.ForeignKey("work_process.id"))
    active = db.Column(db.Boolean, default=True, nullable=False)


class Performance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("plan.id"), nullable=False)
    reporting_period = db.Column(db.String(80), nullable=False)
    progress_percent = db.Column(db.Float, nullable=False, default=0)
    achievement = db.Column(db.Text)
    challenges = db.Column(db.Text)
    next_steps = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Finding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text)
    severity = db.Column(db.String(30), nullable=False, default="Medium")
    status = db.Column(db.String(30), nullable=False, default="Open")
    due_date = db.Column(db.Date)
    owner = db.Column(db.String(160))
    corrective_action = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if current_user.role != "Admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("ቀኑ ትክክለኛ ቅርጽ አይደለም።")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-this-secret")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    # SQLite is for local development only. Render production should set DATABASE_URL.
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///kirkos_lcppme_local.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        seed_reference_data()
        create_initial_admin()

    @app.context_processor
    def inject_globals():
        return {"now_year": datetime.utcnow().year}

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/health")
    def health():
        try:
            db.session.execute(db.select(WorkProcess.id).limit(1)).all()
            return {"status": "ok", "database": "connected"}, 200
        except Exception:
            app.logger.exception("Health check database error")
            return {"status": "error", "database": "unavailable"}, 503

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
            if user and user.active and user.check_password(password):
                login_user(user)
                flash("በተሳካ ሁኔታ ገብተዋል።", "success")
                return redirect(url_for("dashboard"))
            flash("የተጠቃሚ ስም ወይም የይለፍ ቃል ትክክል አይደለም።", "error")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("ከስርዓቱ ወጥተዋል።", "success")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        total_plans = db.session.scalar(db.select(func.count(Plan.id))) or 0
        total_processes = db.session.scalar(db.select(func.count(WorkProcess.id))) or 0
        total_teams = db.session.scalar(db.select(func.count(Team.id))) or 0
        total_kpis = db.session.scalar(db.select(func.count(KPI.id)).where(KPI.active.is_(True))) or 0
        recent_plans = db.session.execute(db.select(Plan).order_by(Plan.created_at.desc()).limit(6)).scalars().all()
        avg_progress = db.session.scalar(db.select(func.avg(Performance.progress_percent))) or 0
        open_findings = db.session.scalar(db.select(func.count(Finding.id)).where(Finding.status != "Closed")) or 0
        return render_template("dashboard.html", total_plans=total_plans, total_processes=total_processes,
                               total_teams=total_teams, total_kpis=total_kpis, recent_plans=recent_plans,
                               avg_progress=round(avg_progress, 1), open_findings=open_findings)

    @app.route("/plans", methods=["GET", "POST"])
    @login_required
    def plans():
        if request.method == "POST":
            try:
                fiscal_year = request.form.get("fiscal_year", "").strip()
                title = request.form.get("title", "").strip()
                objective = request.form.get("objective", "").strip()
                process_id = request.form.get("process_id", type=int)
                team_id = request.form.get("team_id", type=int)
                start_date = parse_date(request.form.get("start_date", ""))
                end_date = parse_date(request.form.get("end_date", ""))
                process = db.session.get(WorkProcess, process_id) if process_id else None
                team = db.session.get(Team, team_id) if team_id else None
                if not fiscal_year or not title or not process:
                    raise ValueError("የበጀት ዓመት፣ የዕቅድ ርዕስና የሥራ ሂደት ማስገባት ግዴታ ነው።")
                if team and team.process_id != process.id:
                    raise ValueError("የተመረጠው ቡድን ከተመረጠው የሥራ ሂደት ጋር አይዛመድም።")
                if start_date and end_date and end_date < start_date:
                    raise ValueError("የመጨረሻ ቀን ከመጀመሪያ ቀን በፊት መሆን አይችልም።")
                plan = Plan(fiscal_year=fiscal_year, title=title, objective=objective or None,
                            process_id=process.id, team_id=team.id if team else None,
                            start_date=start_date, end_date=end_date, status="Draft",
                            created_by=current_user.id)
                db.session.add(plan)
                db.session.commit()
                flash("ዕቅዱ በተሳካ ሁኔታ ተመዝግቧል።", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
            except Exception:
                db.session.rollback()
                app.logger.exception("Plan save failed")
                flash("ዕቅዱን ማስቀመጥ አልተቻለም። የዳታቤዝ ግንኙነትን ያረጋግጡ።", "error")
            return redirect(url_for("plans"))

        process_id = request.args.get("process_id", type=int)
        query = db.select(Plan).order_by(Plan.created_at.desc())
        if process_id:
            query = query.where(Plan.process_id == process_id)
        all_plans = db.session.execute(query).scalars().all()
        return render_template("plans.html", plans=all_plans,
                               processes=db.session.execute(db.select(WorkProcess).order_by(WorkProcess.name)).scalars().all(),
                               teams=db.session.execute(db.select(Team).order_by(Team.name)).scalars().all(),
                               selected_process_id=process_id)

    @app.route("/plans/<int:plan_id>/delete", methods=["POST"])
    @login_required
    def delete_plan(plan_id):
        plan = db.get_or_404(Plan, plan_id)
        if current_user.role != "Admin":
            abort(403)
        db.session.delete(plan)
        db.session.commit()
        flash("ዕቅዱ ተሰርዟል።", "success")
        return redirect(url_for("plans"))

    @app.route("/processes", methods=["GET", "POST"])
    @login_required
    def processes():
        if request.method == "POST":
            code, name = request.form.get("code", "").strip(), request.form.get("name", "").strip()
            if not code or not name:
                flash("ኮድና ስም ያስፈልጋሉ።", "error")
            else:
                try:
                    db.session.add(WorkProcess(code=code, name=name))
                    db.session.commit()
                    flash("የሥራ ሂደቱ ተመዝግቧል።", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("ይህ ኮድ አስቀድሞ ተመዝግቧል።", "error")
            return redirect(url_for("processes"))
        rows = db.session.execute(db.select(WorkProcess).order_by(WorkProcess.name)).scalars().all()
        return render_template("processes.html", processes=rows)

    @app.route("/teams", methods=["GET", "POST"])
    @login_required
    def teams():
        if request.method == "POST":
            code, name = request.form.get("code", "").strip(), request.form.get("name", "").strip()
            process_id = request.form.get("process_id", type=int)
            if not code or not name or not process_id:
                flash("ኮድ፣ ስምና የሥራ ሂደት ያስፈልጋሉ።", "error")
            else:
                try:
                    db.session.add(Team(code=code, name=name, process_id=process_id))
                    db.session.commit()
                    flash("ቡድኑ ተመዝግቧል።", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("ይህ የቡድን ኮድ አስቀድሞ ተመዝግቧል።", "error")
            return redirect(url_for("teams"))
        rows = db.session.execute(db.select(Team).order_by(Team.name)).scalars().all()
        processes = db.session.execute(db.select(WorkProcess).order_by(WorkProcess.name)).scalars().all()
        return render_template("teams.html", teams=rows, processes=processes)

    @app.route("/kpis", methods=["GET", "POST"])
    @login_required
    def kpis():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            unit = request.form.get("unit", "%").strip() or "%"
            description = request.form.get("description", "").strip()
            try:
                target = float(request.form.get("target_value", "0"))
                process_id = request.form.get("process_id", type=int)
                if not name:
                    raise ValueError("የKPI ስም ያስፈልጋል።")
                db.session.add(KPI(name=name, unit=unit, description=description or None,
                                   target_value=target, process_id=process_id))
                db.session.commit()
                flash("KPI ተመዝግቧል።", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc) or "የታለመ ውጤት ቁጥር መሆን አለበት።", "error")
            except Exception:
                db.session.rollback()
                app.logger.exception("KPI save failed")
                flash("KPI ማስቀመጥ አልተቻለም።", "error")
            return redirect(url_for("kpis"))
        rows = db.session.execute(db.select(KPI).order_by(KPI.name)).scalars().all()
        processes = db.session.execute(db.select(WorkProcess).order_by(WorkProcess.name)).scalars().all()
        return render_template("kpis.html", kpis=rows, processes=processes)

    @app.route("/performance", methods=["GET", "POST"])
    @login_required
    def performance():
        if request.method == "POST":
            try:
                plan_id = request.form.get("plan_id", type=int)
                period = request.form.get("reporting_period", "").strip()
                progress = float(request.form.get("progress_percent", "0"))
                if not plan_id or not period:
                    raise ValueError("ዕቅድና የሪፖርት ጊዜ ያስፈልጋሉ።")
                if not 0 <= progress <= 100:
                    raise ValueError("የአፈጻጸም መቶኛ ከ0 እስከ 100 መሆን አለበት።")
                entry = Performance(plan_id=plan_id, reporting_period=period, progress_percent=progress,
                                    achievement=request.form.get("achievement", "").strip() or None,
                                    challenges=request.form.get("challenges", "").strip() or None,
                                    next_steps=request.form.get("next_steps", "").strip() or None,
                                    recorded_by=current_user.id)
                db.session.add(entry)
                db.session.commit()
                flash("የአፈጻጸም መረጃ ተመዝግቧል።", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
            except Exception:
                db.session.rollback()
                app.logger.exception("Performance save failed")
                flash("የአፈጻጸም መረጃውን ማስቀመጥ አልተቻለም።", "error")
            return redirect(url_for("performance"))
        plans_rows = db.session.execute(db.select(Plan).order_by(Plan.title)).scalars().all()
        rows = db.session.execute(db.select(Performance).order_by(Performance.recorded_at.desc())).scalars().all()
        return render_template("performance.html", plans=plans_rows, records=rows)

    @app.route("/findings", methods=["GET", "POST"])
    @login_required
    def findings():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            if not title:
                flash("የችግሩ ርዕስ ያስፈልጋል።", "error")
            else:
                try:
                    due_date = parse_date(request.form.get("due_date", ""))
                    db.session.add(Finding(title=title, details=request.form.get("details", "").strip() or None,
                        severity=request.form.get("severity", "Medium"), owner=request.form.get("owner", "").strip() or None,
                        corrective_action=request.form.get("corrective_action", "").strip() or None, due_date=due_date))
                    db.session.commit()
                    flash("ችግሩና የማስተካከያ እርምጃው ተመዝግቧል።", "success")
                except Exception:
                    db.session.rollback()
                    app.logger.exception("Finding save failed")
                    flash("መረጃውን ማስቀመጥ አልተቻለም።", "error")
            return redirect(url_for("findings"))
        rows = db.session.execute(db.select(Finding).order_by(Finding.created_at.desc())).scalars().all()
        return render_template("findings.html", findings=rows)

    @app.route("/findings/<int:finding_id>/status", methods=["POST"])
    @login_required
    def update_finding_status(finding_id):
        row = db.get_or_404(Finding, finding_id)
        status = request.form.get("status", "")
        if status not in {"Open", "In Progress", "Closed"}:
            abort(400)
        row.status = status
        db.session.commit()
        flash("የችግሩ ሁኔታ ተሻሽሏል።", "success")
        return redirect(url_for("findings"))

    @app.route("/reports")
    @login_required
    def reports():
        plans_count = db.session.scalar(db.select(func.count(Plan.id))) or 0
        perf_count = db.session.scalar(db.select(func.count(Performance.id))) or 0
        findings_count = db.session.scalar(db.select(func.count(Finding.id))) or 0
        closed_count = db.session.scalar(db.select(func.count(Finding.id)).where(Finding.status == "Closed")) or 0
        return render_template("reports.html", plans_count=plans_count, perf_count=perf_count,
                               findings_count=findings_count, closed_count=closed_count)

    @app.route("/users", methods=["GET", "POST"])
    @login_required
    @admin_required
    def users():
        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            role = request.form.get("role", "Staff")
            if not full_name or not username or len(password) < 10 or role not in {"Admin", "Manager", "Staff"}:
                flash("ሁሉንም መስኮች ይሙሉ፤ የይለፍ ቃል ቢያንስ 10 ቁምፊ ይሁን።", "error")
            else:
                try:
                    user = User(full_name=full_name, username=username, role=role)
                    user.set_password(password)
                    db.session.add(user)
                    db.session.commit()
                    flash("ተጠቃሚው ተመዝግቧል።", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("ይህ የተጠቃሚ ስም ተይዟል።", "error")
            return redirect(url_for("users"))
        rows = db.session.execute(db.select(User).order_by(User.full_name)).scalars().all()
        return render_template("users.html", users=rows)

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="ይህን ተግባር ለመፈጸም ፈቃድ የለዎትም።"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="የጠየቁት ገጽ አልተገኘም።"), 404

    return app


def seed_reference_data():
    if db.session.scalar(db.select(func.count(WorkProcess.id))) == 0:
        processes = [
            WorkProcess(code="TP-EDU", name="ታክስ ከፋዮች ትምህርት፣ ድጋፍና የሕግ ተገዥነት"),
            WorkProcess(code="TAX-INFO", name="ታክስ መረጃ"),
            WorkProcess(code="TAX-BASE", name="የታክስ መሠረቶች ማሻሻያና ማስፋፊያ"),
        ]
        db.session.add_all(processes)
        db.session.flush()
        team_rows = [
            ("EDU-01", "የታክስ ከፋዮች ትምህርት", processes[0].id),
            ("EDU-02", "የሕግ ተገዥነት ክትትል", processes[0].id),
            ("INFO-01", "ደረሰኝና ሽያጭ መመዝገቢያ መሣሪያ አጠቃቀም", processes[1].id),
            ("INFO-02", "የታክስ መረጃ ስብስብና ማረጋገጥ", processes[1].id),
            ("BASE-01", "የታክስ መሠረት ማስፋፊያ", processes[2].id),
            ("BASE-02", "ያልተመዘገቡ ታክስ ከፋዮች መለየት", processes[2].id),
        ]
        db.session.add_all([Team(code=c, name=n, process_id=p) for c, n, p in team_rows])
        db.session.commit()


def create_initial_admin():
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    existing = db.session.scalar(db.select(User).where(User.username == username))
    if not existing and password:
        user = User(full_name="System Administrator", username=username, role="Admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
