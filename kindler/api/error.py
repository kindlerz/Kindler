from flask import render_template, Blueprint, request

from kindler.abuse import BLOCK_TTL_SECONDS, DAILY_QUOTA

error_bp = Blueprint("error", __name__, url_prefix="/error")


@error_bp.route("")
def error():
    url = request.args.get("url")
    status_code = request.args.get("status_code")
    reason = request.args.get("reason")
    message = map_status_code_to_error(status_code, reason)
    html = render_template("error.html", message=message, url=url)
    if status_code == "429" or (status_code == "403" and reason == "network"):
        headers = {"Retry-After": str(BLOCK_TTL_SECONDS)} if status_code == "429" else {}
        return html, int(status_code), headers
    return html


def map_status_code_to_error(status_code, reason=None):
    match status_code:
        case "400":
            return "Please provide a URL to clean (400)"
        case "401":
            return "Website denied access (401)"
        case "403" if reason == "network":
            return "Datacenter or VPN connection detected. Please turn off your VPN or use a regular home connection (403)"
        case "403":
            return "Website denied access (403)"
        case "404":
            return "Page not found (404)"
        case "429":
            return f"Daily limit of {DAILY_QUOTA} conversions reached. Please try again later (429)"
        case "500":
            return "Encountered internal error (500)"
        case _:
            return None
