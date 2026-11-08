from flask import render_template, Blueprint, Response, current_app, send_from_directory

home_bp = Blueprint("home", __name__)

ROBOTS_TXT = """\
User-agent: ClaudeBot
User-agent: Claude-SearchBot
User-agent: Claude-User
Disallow: /
"""


@home_bp.route("/")
def home():
    return render_template("home.html")


@home_bp.route("/robots.txt")
def robots():
    return Response(ROBOTS_TXT, mimetype="text/plain")


@home_bp.route("/favicon.ico")
def favicon():
    return send_from_directory(
        current_app.static_folder, "favicon.ico", mimetype="image/x-icon"
    )
