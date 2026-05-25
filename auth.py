from functools import wraps
from flask import current_app, request, jsonify, session, redirect, url_for, make_response


def init_auth(app, db_conn, lock):
    """初始化 auth 模块，将 DB 连接注入 Flask 配置"""
    app.config["DB_CONN"] = db_conn
    app.config["DB_LOCK"] = lock


def _get_db():
    db = current_app.config.get("DB_CONN")
    lk = current_app.config.get("DB_LOCK")
    return db, lk


def _extract_token():
    """从请求中提取 API 令牌：优先 Authorization header，其次 query param"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.args.get("token")


def api_token_required(f):
    """API 路由装饰器：验证 Bearer token / ?token= 后才能访问"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({"error": "未授权，需要 API 令牌"}), 401

        db, lk = _get_db()
        if not db:
            return jsonify({"error": "服务未初始化"}), 500

        with lk:
            c = db.cursor()
            c.execute("SELECT value FROM api_settings WHERE key = 'api_token'")
            row = c.fetchone()

        if not row or token != row[0]:
            return jsonify({"error": "API 令牌无效"}), 401

        return f(*args, **kwargs)

    return wrapper


def login_required(f):
    """Web 页面路由装饰器：验证 session 登录后才能访问"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("console_user"):
            return redirect(url_for("console.login"))
        return f(*args, **kwargs)

    return wrapper


def api_or_session_required(f):
    """API 路由装饰器：验证 Bearer token/?token= 或控制台 session 后访问"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        # 1) Try API token first
        token = _extract_token()
        if token:
            db, lk = _get_db()
            if db:
                with lk:
                    c = db.cursor()
                    c.execute("SELECT value FROM api_settings WHERE key = 'api_token'")
                    row = c.fetchone()
                if row and token == row[0]:
                    return f(*args, **kwargs)

        # 2) Try console session
        if session.get("console_user"):
            return f(*args, **kwargs)

        return jsonify({"error": "未授权，需要 API 令牌或登录控制台"}), 401

    return wrapper

def get_api_token():
    """从数据库读取当前 API 令牌明文，用于页面注入"""
    db, lk = _get_db()
    if not db:
        return None
    with lk:
        c = db.cursor()
        c.execute("SELECT value FROM api_settings WHERE key = 'api_token'")
        row = c.fetchone()
    return row[0] if row else None


def get_console_user(username):
    """查询控制台用户（含角色）"""
    db, lk = _get_db()
    with lk:
        c = db.cursor()
        c.execute(
            "SELECT id, username, password_hash, role FROM console_users WHERE username = ?",
            (username,),
        )
        return c.fetchone()


def get_current_user_role():
    """返回当前登录用户的角色，未登录返回 None"""
    username = session.get("console_user")
    if not username:
        return None
    row = get_console_user(username)
    return row[3] if row else None


def admin_required(f):
    """Web 页面路由装饰器：仅允许超级管理员访问"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("console_user"):
            return redirect(url_for("console.login"))
        role = get_current_user_role()
        if role != "admin":
            return make_response("无权访问，仅限超级管理员", 403)
        return f(*args, **kwargs)

    return wrapper


def role_at_least(min_role):
    """检查当前用户角色是否达到指定级别。admin > senior > junior"""
    levels = {"admin": 3, "senior": 2, "junior": 1}
    required = levels.get(min_role, 1)
    role = get_current_user_role()
    user_level = levels.get(role, 0)
    return user_level >= required


def can_access_instance(allowed_roles_str):
    """检查当前用户是否有权访问指定 allowed_roles 的实例"""
    role = get_current_user_role()
    if role == "admin":
        return True
    allowed = [x.strip() for x in (allowed_roles_str or "").split(",") if x.strip()]
    return role in allowed


def role_at_least(min_role):
    """检查当前用户角色是否达到指定级别。admin > senior > junior"""
    levels = {"admin": 3, "senior": 2, "junior": 1}
    required = levels.get(min_role, 1)
    role = get_current_user_role()
    user_level = levels.get(role, 0)
    return user_level >= required


def can_access_instance(allowed_roles_str):
    """检查当前用户是否有权访问指定 allowed_roles 的实例"""
    role = get_current_user_role()
    if role == "admin":
        return True
    allowed = [x.strip() for x in (allowed_roles_str or "").split(",") if x.strip()]
    return role in allowed
