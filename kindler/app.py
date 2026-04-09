import logging

from flask import Flask, redirect, url_for
from flask_healthz import healthz
from logging.config import dictConfig

from kindler.api.error import error_bp
from kindler.api.gemini import gemini_bp
from kindler.api.gutenberg_au_project import gutenberg_au_bp
from kindler.api.gutenberg_project import gutenberg_bp
from kindler.api.home import home_bp
from kindler.api.news import news_bp
from kindler.api.standard_ebooks import standard_ebooks_bp
from kindler.api.web import web_bp
from kindler.api.wikipedia import wikipedia_bp
from kindler.api.youtube import youtube_bp
from kindler.cache import cache, CACHE_CONFIG


dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
        "loggers": {
            "flask.app": {"level": "INFO", "handlers": ["wsgi"], "propagate": False}
        },
    }
)
logging.info("Starting Flask app...")

app = Flask(__name__)


def liveness():
    return True, {"status": "up"}


def readiness():
    return True, {"status": "up"}


app.config.update(CACHE_CONFIG)
app.config.update(HEALTHZ={"live": liveness, "ready": readiness})

cache.init_app(app)

app.register_blueprint(web_bp)
app.register_blueprint(gemini_bp)
app.register_blueprint(news_bp)
app.register_blueprint(gutenberg_bp)
app.register_blueprint(gutenberg_au_bp)
app.register_blueprint(standard_ebooks_bp)
app.register_blueprint(wikipedia_bp)
app.register_blueprint(youtube_bp)
app.register_blueprint(home_bp)
app.register_blueprint(error_bp)
app.register_blueprint(healthz, url_prefix="/healthz")


@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for("error.error", status_code=404))


if __name__ == "__main__":
    app.run(debug=True)
    # uncomment to be able to access the app via other devices on router
    # app.run(host="0.0.0.0", port=5000, debug=True)
