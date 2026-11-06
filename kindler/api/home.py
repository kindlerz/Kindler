from flask import render_template, Blueprint, Response

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
