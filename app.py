from flask import Flask, render_template, redirect, request, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from datetime import datetime, date
from urllib.parse import urlparse, urljoin
from functools import wraps
from models import db, User, Task
import pandas as pd
import io
from flask import send_file
from flask import render_template, make_response
from xhtml2pdf import pisa
from io import BytesIO
from models import User
from werkzeug.utils import secure_filename
import os
from models import User, Task  




app = Flask(__name__)
app.secret_key = "secret_key_123"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

@app.route("/")
@login_required
def index():
    keyword = request.args.get("q", "")
    query = Task.query.filter_by(user_id=current_user.id)
    if keyword:
        query = query.filter(Task.content.ilike(f"%{keyword}%"))
    tasks = query.all()
    return render_template("index.html", tasks=tasks, today=date.today())

@app.route("/add", methods=["POST"])
@login_required
def add():
    content = request.form.get("task")
    deadline = request.form.get("deadline")
    if content:
        new_task = Task(
            content=content,
            user_id=current_user.id,
            deadline=datetime.strptime(deadline, "%Y-%m-%d").date() if deadline else None
        )
        db.session.add(new_task)
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        return redirect(url_for("index"))

    if request.method == "POST":
        task.content = request.form.get("content")
        deadline = request.form.get("deadline")
        task.deadline = datetime.strptime(deadline, "%Y-%m-%d").date() if deadline else None
        db.session.commit()
        return redirect(url_for("index"))

    return render_template("edit.html", task=task)

@app.route("/delete/<int:task_id>")
@login_required
def delete(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id == current_user.id:
        db.session.delete(task)
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/done/<int:task_id>")
@login_required
def mark_done(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id == current_user.id:
        task.is_done = not task.is_done
        db.session.commit()
    return redirect(url_for("index"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        print(f"User ditemukan: {user}")
        if user and check_password_hash(user.password, password):
            print("Password cocok, login_user dipanggil")
            login_user(user)

            # ✅ Cek next parameter dari URL
            next_page = request.args.get("next")
            if next_page and is_safe_url(next_page):
                print("Redirect ke next_page:", next_page)
                return redirect(next_page)

            # ✅ Cek role admin
            print("Role user:", user.role)
            if user.role == "admin":
                print("Redirect ke dashboard admin")
                return redirect(url_for("admin_dashboard"))

            # Jika bukan admin
            return redirect(url_for("index"))

        flash('Username atau password salah', 'danger')
    return render_template('login.html')

#sementara
@app.route("/debug_user")
def debug_user():
    return {
        "authenticated": current_user.is_authenticated,
        "user_id": current_user.get_id(),
        "username": getattr(current_user, "username", None),
        "is_active": getattr(current_user, "is_active", None)
    }

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username sudah digunakan, coba yang lain.")
            return redirect(url_for("register"))

        password = generate_password_hash(request.form["password"])
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.commit()
        flash("Registrasi berhasil! Silakan login.")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/calendar")
@login_required
def calendar_view():
    return render_template("calendar.html")

@app.route("/api/tasks")
@login_required
def api_tasks():
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    events = []
    for task in tasks:
        if task.deadline:
            events.append({
                "title": task.content,
                "start": task.deadline.strftime("%Y-%m-%d"),
                "color": "#28a745" if task.is_done else "#dc3545"
            })
    return jsonify(events=events)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Silakan login dulu.", "warning")
            return redirect(url_for('login'))
        if current_user.role != "admin":
            flash("Akses hanya untuk admin.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    keyword = request.args.get("q", "")
    role_filter = request.args.get("role", "")
    sort_order = request.args.get("sort", "asc")

    query = User.query
    if keyword:
        query = query.filter(User.username.ilike(f"%{keyword}%"))
    if role_filter:
        query = query.filter_by(role=role_filter)
    if sort_order == "desc":
        query = query.order_by(User.username.desc())
    else:
        query = query.order_by(User.username.asc())

    users = query.all()
    tasks = Task.query.all()
    admin_count = User.query.filter_by(role="admin").count()
    user_count = User.query.filter_by(role="user").count()
    total_users = len(users)
    total_tasks = len(tasks)
    completed_tasks = Task.query.filter_by(is_done=True).count()
    pending_tasks = Task.query.filter_by(is_done=False).count()

    return render_template(
        "admin_dashboard.html",
        users=users,
        tasks=tasks,
        total_users=total_users,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        admin_count=admin_count,
        user_count=user_count
    )

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("tidak bisa hapus akun sendiri", "warning")
        return redirect(url_for("admin_dashboard"))
    Task.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("user berhasil dihapus", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/edit_user/<int:user_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        user.username = request.form.get("username")
        user.role = request.form.get("role")
        db.session.commit()
        flash("User berhasil diupdate", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("edit_user.html", user=user)

@app.route("/admin/toggle_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    flash("Status user diperbarui.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route('/export/users')
def export_users():
    users = User.query.all()
    data = [{
        'ID': u.id,
        'Username': u.username,
        'Role': u.role,
        'Status Aktif': 'Aktif' if u.is_active else 'Nonaktif'
    } for u in users]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(output, download_name='users.xlsx', as_attachment=True)

@app.route('/import-tasks', methods=['POST'])
@login_required
@admin_required
def import_tasks():
    file = request.files['excel_file']
    if not file or not file.filename.endswith('.xlsx'):
        flash('File tidak valid. Harus .xlsx', 'danger')
        return redirect(url_for('admin_dashboard'))

    filename = secure_filename(file.filename)
    filepath = os.path.join('uploads', filename)
    os.makedirs('uploads', exist_ok=True)
    file.save(filepath)

    try:
        df = pd.read_excel(filepath)
        for index, row in df.iterrows():
            username = row['Pengguna']
            user = User.query.filter_by(username=username).first()
            if user:
                new_task = Task(
                    user_id=user.id,
                    content=row['Tugas'],
                    deadline=row['Deadline'] if not pd.isna(row['Deadline']) else None,
                    is_done=True if str(row['Status']).strip().lower() == 'selesai' else False
                )
                db.session.add(new_task)
        db.session.commit()
        flash('Data tugas berhasil diimpor!', 'success')
    except Exception as e:
        flash(f'Gagal mengimpor: {e}', 'danger')
    finally:
        os.remove(filepath)

    return redirect(url_for('admin_dashboard'))

if __name__ == "__main__":
    with app.app_context():
        app.run(debug=True)
