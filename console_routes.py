from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    make_response,
)
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
import secrets

from auth import login_required, admin_required, get_api_token, get_console_user, get_current_user_role

console_bp = Blueprint("console", __name__, url_prefix="/console")


def _get_db():
    from flask import current_app

    return current_app.config["DB_CONN"], current_app.config["DB_LOCK"]


# ── 登录 ──


@console_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # Always show login form; if already logged in, show a note
        logged_in_user = session.get("console_user")
        extra_note = f"\u5f53\u524d\u5df2\u767b\u5f55\u4e3a {logged_in_user}\uff0c\u8bf7\u91cd\u65b0\u767b\u5f55\u4ee5\u5207\u6362\u8d26\u53f7\u3002" if logged_in_user else None
        resp = make_response(render_template("console_login.html", error=None, logged_in_hint=extra_note))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    username = (request.form.get("user_login") or "").strip()
    password = request.form.get("user_pass") or ""

    row = get_console_user(username) if username else None
    if not row:
        return make_response(render_template("console_login.html", error="账号或密码错误"))

    _, db_user, pw_hash, db_role = row
    if not check_password_hash(pw_hash, password):
        return make_response(render_template("console_login.html", error="账号或密码错误"))

    session["console_user"] = db_user
    session["console_role"] = db_role
    return redirect(url_for("index"))


@console_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("console_user", None)
    return redirect(url_for("console.login"))


# ── 主页 ──


@console_bp.route("")
@login_required
def index():
    resp = make_response(
        render_template("console_index.html", username=session.get("console_user"), role=session.get("console_role"))
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ── API 令牌设置 ──


@console_bp.route("/settings")
@login_required
@admin_required
def settings():
    resp = make_response(
        render_template("console_settings.html", username=session.get("console_user"))
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@console_bp.route("/api/settings/token", methods=["GET", "POST"])
@login_required
@admin_required
def api_settings_token():
    db, lk = _get_db()

    if request.method == "GET":
        token = get_api_token()
        return jsonify({"token": token if token else ""})

    # POST：重新生成令牌
    new_token = secrets.token_urlsafe(32)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with lk:
        c = db.cursor()
        c.execute(
            "INSERT OR REPLACE INTO api_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("api_token", new_token, now),
        )
        db.commit()
    return jsonify({"token": new_token})


# ── 密码修改 ──


@console_bp.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    """修改当前登录用户的密码"""
    data = request.get_json(silent=True) or {}
    old_pw = (data.get("old_password") or "").strip()
    new_pw = (data.get("new_password") or "").strip()

    if not old_pw or not new_pw:
        return jsonify({"error": "请填写旧密码和新密码"}), 400
    if len(new_pw) < 4:
        return jsonify({"error": "新密码至少 4 位"}), 400

    username = session.get("console_user")
    row = get_console_user(username)
    if not row:
        return jsonify({"error": "用户不存在"}), 404

    _, db_user, pw_hash, db_role = row
    if not check_password_hash(pw_hash, old_pw):
        return jsonify({"error": "旧密码错误"}), 403

    new_hash = generate_password_hash(new_pw)
    db, lk = _get_db()
    with lk:
        c = db.cursor()
        c.execute("UPDATE console_users SET password_hash = ? WHERE username = ?", (new_hash, username))
        db.commit()
    return jsonify({"ok": True, "message": "密码已修改"})


# ── 监控实例管理 ──


@console_bp.route("/api/instances", methods=["GET", "POST"])
@login_required
def instances():
    db, lk = _get_db()

    if request.method == "GET":
        with lk:
            c = db.cursor()
            c.execute(
                "SELECT id, name, base_url, metrics_url, notes, token, allowed_roles FROM monitor_instances ORDER BY id DESC"
            )
            rows = c.fetchall()
        items = []
        user_role = get_current_user_role()
        for r in rows:
            allowed_raw = r[6] if len(r) > 6 else "admin,senior,junior"
            allowed_roles = [x.strip() for x in allowed_raw.split(",") if x.strip()]
            if user_role == "admin" or user_role in allowed_roles:
                items.append({
                    "id": r[0], "name": r[1], "base_url": r[2],
                    "metrics_url": r[3], "notes": r[4],
                    "token": r[5] if len(r) > 5 else "",
                    "allowed_roles": allowed_raw,
                })
        return jsonify({"items": items})

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    metrics_url = (data.get("metrics_url") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None
    token = (data.get("token") or "").strip()
    allowed_roles = (data.get("allowed_roles") or "admin,senior,junior").strip()

    if not name or not base_url:
        return jsonify({"error": "name/base_url required"}), 400
    if not token:
        return jsonify({"error": "API 令牌不能为空"}), 400
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return jsonify({"error": "base_url must start with http:// or https://"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with lk:
        c = db.cursor()
        c.execute(
            "INSERT INTO monitor_instances (name, base_url, metrics_url, notes, token, allowed_roles, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, base_url, metrics_url, notes, token, allowed_roles, now, now),
        )
        db.commit()
    return jsonify({"ok": True})


@console_bp.route("/api/instances/<int:instance_id>", methods=["PUT", "DELETE"])
@login_required
def instance_item(instance_id):
    db, lk = _get_db()

    if request.method == "DELETE":
        with lk:
            c = db.cursor()
            c.execute("DELETE FROM monitor_instances WHERE id = ?", (instance_id,))
            db.commit()
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    metrics_url = (data.get("metrics_url") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None
    token = (data.get("token") or "").strip()
    allowed_roles = (data.get("allowed_roles") or "admin,senior,junior").strip()

    if not name or not base_url:
        return jsonify({"error": "name/base_url required"}), 400
    if not token:
        return jsonify({"error": "API 令牌不能为空"}), 400
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return jsonify({"error": "base_url must start with http:// or https://"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with lk:
        c = db.cursor()
        c.execute(
            "UPDATE monitor_instances SET name = ?, base_url = ?, metrics_url = ?, notes = ?, token = ?, allowed_roles = ?, updated_at = ? WHERE id = ?",
            (name, base_url, metrics_url, notes, token, allowed_roles, now, instance_id),
        )
        db.commit()
    return jsonify({"ok": True})


# ── 用户管理（仅超级管理员）──


@console_bp.route("/users")
@login_required
@admin_required
def users_page():
    resp = make_response(
        render_template("console_users.html", username=session.get("console_user"))
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@console_bp.route("/api/users", methods=["GET", "POST"])
@login_required
@admin_required
def api_users():
    db, lk = _get_db()

    if request.method == "GET":
        with lk:
            c = db.cursor()
            c.execute(
                "SELECT id, username, role, created_at FROM console_users ORDER BY id ASC"
            )
            rows = c.fetchall()
        items = [
            {"id": r[0], "username": r[1], "role": r[2], "created_at": r[3]}
            for r in rows
        ]
        return jsonify({"items": items})

    # POST: 创建新用户
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "junior").strip()

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    if len(password) < 4:
        return jsonify({"error": "密码长度至少 4 位"}), 400
    if role not in ("admin", "senior", "junior"):
        role = "junior"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pw_hash = generate_password_hash(password)
    try:
        with lk:
            c = db.cursor()
            c.execute(
                "INSERT INTO console_users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, pw_hash, role, now),
            )
            db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": f"创建失败（用户名可能已存在）: {str(e)}"}), 400


@console_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
@admin_required
def api_user_delete(user_id):
    db, lk = _get_db()
    with lk:
        c = db.cursor()
        # 不允许删除超级管理员
        c.execute("SELECT username, role FROM console_users WHERE id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "用户不存在"}), 404
        if row[1] == "admin":
            return jsonify({"error": "不能删除超级管理员"}), 400
        c.execute("DELETE FROM console_users WHERE id = ?", (user_id,))
        db.commit()
    return jsonify({"ok": True})


@console_bp.route("/api/users/<int:user_id>/role", methods=["PATCH"])
@login_required
@admin_required
def api_user_role(user_id):
    """修改用户角色"""
    data = request.get_json(silent=True) or {}
    new_role = (data.get("role") or "").strip()
    if new_role not in ("admin", "senior", "junior"):
        return jsonify({"error": "无效的角色"}), 400

    db, lk = _get_db()
    with lk:
        c = db.cursor()
        c.execute("SELECT username, role FROM console_users WHERE id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"error": "用户不存在"}), 404
        # yofc 必须保持 admin
        if row[0] == "yofc" and new_role != "admin":
            return jsonify({"error": "不能降级 yofc 超级管理员角色"}), 400
        c.execute("UPDATE console_users SET role = ? WHERE id = ?", (new_role, user_id))
        db.commit()
    return jsonify({"ok": True, "message": f"角色已更新为 {new_role}"})

@console_bp.route("/api/instances/verify", methods=["POST"])
@login_required
def verify_instance():
    """验证实例的 API 令牌是否有效"""
    data = request.get_json(silent=True) or {}
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    token = (data.get("token") or "").strip()

    if not base_url:
        return jsonify({"ok": False, "message": "请输入 Base URL"}), 400
    if not token:
        return jsonify({"ok": False, "message": "请输入 API 令牌"}), 400

    import urllib.request
    import ssl
    test_url = f"{base_url}/api/gpu-info"
    req = urllib.request.Request(test_url, headers={"Authorization": f"Bearer {token}"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        urllib.request.urlopen(req, timeout=5, context=ctx)
        return jsonify({"ok": True, "message": "✓ 连接成功，令牌有效"})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({"ok": False, "message": "✗ 令牌无效（HTTP 401）"})
        return jsonify({"ok": False, "message": f"✗ 连接失败（HTTP {e.code}）"})
    except urllib.error.URLError as e:
        return jsonify({"ok": False, "message": f"✗ 连接失败（{e.reason}）"})
    except Exception as e:
        return jsonify({"ok": False, "message": f"✗ {str(e)}"})