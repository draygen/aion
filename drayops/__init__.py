from pathlib import Path

from flask import Flask

from .api import api_bp


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["DRAYOPS_BASE_DIR"] = base_dir
    app.register_blueprint(api_bp)
    return app
