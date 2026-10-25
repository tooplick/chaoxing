# -*- coding: utf-8 -*-
"""Web 多账号平台入口.

    python app.py [--host 0.0.0.0] [--port 5000]

- 开发模式: 前端 `cd frontend && npm run dev` (Vite 代理 /api 到本进程)
- 生产模式: 先 `npm run build`, 本进程直接托管 frontend/dist
- 监听非本机地址时, 必须已设置管理员口令(环境变量 CHAOXING_ADMIN_PASSWORD 或首次本机访问时设置)
"""
import argparse
import os
import secrets
import sys

from flask import Flask, jsonify, send_from_directory

from web.api import bp, init_deps
from web.auth import AuthManager
from web.runner import RunManager
from web.store import Store

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, "frontend", "dist")


def load_secret_key(data_dir: str) -> str:
    path = os.path.join(data_dir, "secret_key")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key


def create_app(data_dir: str | None = None) -> Flask:
    store = Store(data_dir)
    auth = AuthManager(store.data_dir)
    runner = RunManager(store)

    # static_url_path 置空: /assets/xxx 直接映射到 dist/assets/xxx (Vite 产物结构)
    app = Flask(__name__, static_folder=DIST_DIR, static_url_path="")
    app.secret_key = load_secret_key(store.data_dir)
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False

    init_deps(store, auth, runner)
    app.register_blueprint(bp)

    # 服务退出时终止所有任务子进程, 避免孤儿进程继续运行
    import atexit

    atexit.register(runner.kill_all)

    @app.route("/")
    def index():
        if os.path.exists(os.path.join(DIST_DIR, "index.html")):
            return send_from_directory(DIST_DIR, "index.html")
        return jsonify({
            "error": "前端未构建",
            "hint": "cd frontend && npm install && npm run build, 或开发时使用 npm run dev",
        }), 503

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="chaoxing Web 多账号平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="监听端口 (默认 5000)")
    args = parser.parse_args()

    app = create_app()
    auth = AuthManager(Store().data_dir)

    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if args.host not in local_hosts and not auth.is_initialized():
        print(
            f"[启动失败] 监听 {args.host} 前必须设置管理员口令:\n"
            f"  方式一: 设置环境变量 CHAOXING_ADMIN_PASSWORD=<你的口令>\n"
            f"  方式二: 先以 --host 127.0.0.1 启动, 在页面上完成口令初始化后重启",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f" * chaoxing Web 平台: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
