import logging
from datetime import datetime

import requests
import yt_dlp
from flask import render_template, Blueprint, request, Response, stream_with_context
from kindler.util import HEADERS
import re
import unicodedata

youtube_bp = Blueprint("youtube", __name__, url_prefix="/youtube")

INVIDIOUS_SEARCH_URL = "https://inv.thepixora.com/api/v1"


@youtube_bp.route("/")
def home():
    return render_template("index_youtube.html")


@youtube_bp.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        logging.warning("Search query is empty.")
        return "Please provide a search query.", 400
    results = parse_search_result(search_youtube(query))
    return render_template("result_youtube.html", query=query, results=results)


@youtube_bp.route("/play")
def play_page():
    query = request.args.get("q")
    video_id = request.args.get("id")
    is_https = bool(request.is_secure)
    if not video_id:
        logging.warning("Video ID is empty.")
        return "Please provide a YouTube video id.", 400
    try:
        video = get_video(get_youtube_video(video_id))
    except:
        logging.error("Failed to get from yt-dlp, falling back to ")
        video = get_video_fallback(get_youtube_video_fallback(video_id))
    video["is_https"] = is_https
    return render_template("play_youtube.html", query=query, video=video)


@youtube_bp.route("/proxy_youtube")
def proxy_youtube():
    video_url = request.args.get("url")
    if not video_url:
        return "Missing url", 400

    headers = {
        "User-Agent": request.headers.get("User-Agent", ""),
    }

    # Forward Range header if present
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    r = requests.get(video_url, headers=headers, stream=True)

    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    response = Response(stream_with_context(generate()), status=r.status_code)

    # Forward important headers
    for h in [
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
    ]:
        if h in r.headers:
            response.headers[h] = r.headers[h]

    return response


@youtube_bp.route("/proxy_download")
def proxy_download():
    video_url = request.args.get("url")
    if not video_url:
        return "Missing url", 400
    raw_title = request.args.get("title", "")
    filename = sanitize_filename(raw_title)
    headers = {
        "User-Agent": request.headers.get("User-Agent", ""),
    }
    r = requests.get(video_url, headers=headers, stream=True, timeout=60)

    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    response = Response(stream_with_context(generate()), mimetype="video/mp4")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    if "Content-Length" in r.headers:
        response.headers["Content-Length"] = r.headers["Content-Length"]
    return response


def sanitize_filename(title, ext="mp4", max_len=25):
    title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    title = re.sub(r"[^a-zA-Z0-9]", "-", title)
    title = re.sub(r"-+", "-", title)
    title = title.strip("-")
    if not title:
        title = "video"
    if len(title) > max_len:
        title = title[:max_len].rstrip("-")
    return f"{title}.{ext}"


def search_youtube(query: str):
    ydl_opts = {"quiet": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch10:{query}", download=False)
    return info["entries"]


def parse_search_result(search_result):
    result = []
    for item in search_result:
        if item.get("_type") != "url":
            continue
        video_id = item.get("id")
        author = item.get("channel")
        title = item.get("title")
        channel_url = item.get("channel_url")
        channel_name = item.get("channel")
        description = item.get("description")
        duration = format_duration(item.get("duration"))
        published_year = item.get("published_year")
        live_status = item.get("live_status")
        if live_status == "is_live":
            live_status = "LIVE"
        elif live_status == "was_live":
            live_status = "STREAMED"
        else:
            live_status = None
        view_count = item.get("view_count")
        if not view_count and live_status == "LIVE":
            view_count = item.get("concurrent_view_count")
        view_count = format_views(view_count)
        thumb_url = None
        thumbnails = item.get("thumbnails", [])
        for t in thumbnails:
            if t.get("width") == 360:
                thumb_url = t.get("url")
                break
        if not thumb_url:
            for t in thumbnails:
                if t.get("width") == 720:
                    thumb_url = t.get("url")
                    break
        result.append(
            {
                "video_id": video_id,
                "author": author,
                "title": title,
                "channel_url": channel_url,
                "channel_name": channel_name,
                "thumbnail": thumb_url,
                "description": description,
                "view_count": view_count,
                "published_year": published_year,
                "duration": duration,
                "live_status": live_status,
            }
        )
    return result


def get_youtube_video(video_id: str):
    ydl_opts = {
        "quiet": True,
        "format": "best[ext=mp4][height<=480][acodec!='none'][vcodec!='none']",
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "compat_opts": ["no-youtube-unavailable-videos"],
        "remote_components": "ejs:github",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    return info


def get_video(video_details):
    if (
        video_details.get("url") is not None
        and video_details.get("url") is not "none"
        and video_details.get("height") <= 480
        and video_details.get("acodec") != "none"
        and video_details.get("vcodec") != "none"
    ):
        video_play_url = video_details.get("url")
    else:
        video_play_url = pick_video_url(video_details)
    return {
        "video_play_url": video_play_url,
        "description": video_details.get("description"),
        "title": video_details.get("title"),
        "published_text": format_upload_date(video_details.get("upload_date")),
        "view_count": format_views(video_details.get("view_count")),
        "channel_name": video_details.get("channel"),
        "subscriber_count": format_subscribers(
            video_details.get("channel_follower_count")
        ),
        "channel_url": video_details.get("channel_url"),
        "youtube_video_link": video_details.get("webpage_url"),
    }


def format_duration(seconds):
    if not seconds:
        return "N/A"
    seconds = int(seconds)  # make sure it’s an integer
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def format_subscribers(subscriber_count):
    subscriber_count = int(subscriber_count)
    if subscriber_count >= 1_000_000:
        val = subscriber_count / 1_000_000
        # 2 decimal points if <10M, else 1
        if subscriber_count < 10_000_000:
            return f"{val:.2f}M".rstrip("0").rstrip(".")
        else:
            return f"{val:.1f}M".rstrip("0").rstrip(".")
    elif subscriber_count >= 1_000:
        val = subscriber_count / 1_000
        return f"{val:.1f}K".rstrip("0").rstrip(".")
    else:
        return str(subscriber_count)


def format_upload_date(publish_date):
    return datetime.strptime(publish_date, "%Y%m%d").strftime("%b %-d, %Y")


def format_views(view_count):
    if not view_count:
        return None
    view_count = int(view_count)
    if view_count >= 1_000_000_000:
        return f"{view_count / 1_000_000_000:.1f}B".rstrip("0").rstrip(".")
    elif view_count >= 1_000_000:
        return f"{view_count / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    elif view_count >= 1_000:
        return f"{view_count / 1_000:.1f}K".rstrip("0").rstrip(".")
    else:
        return str(view_count)


def pick_video_url(info):
    formats = info.get("formats", [])
    for info_format in formats:
        if match(info_format, 480, "mp4"):
            return info_format["url"]
        if match(info_format, 360, "mp4"):
            return info_format["url"]
    return formats[0]["url"] if formats else None


def match(info_format, height=None, ext="mp4"):
    return (
        info_format.get("height") == height
        and info_format.get("ext") == ext
        and info_format.get("vcodec") != "none"
        and info_format.get("acodec") != "none"
    )


def get_youtube_video_fallback(video_id: str):
    response = requests.get(
        f"{INVIDIOUS_SEARCH_URL}/videos/{video_id}",
        headers=HEADERS,
        timeout=30,
    )
    return response.json()


def get_video_fallback(video_details):
    video_play_url = pick_video_url_fallback(video_details)
    return {
        "video_play_url": video_play_url,
        "description": video_details.get("description"),
        "title": video_details.get("title"),
        "published_text": video_details.get("publishedText"),
        "view_count": format_views(video_details.get("viewCount")),
        "channel_name": video_details.get("author"),
        "subscriber_count": video_details.get("subCountText"),
        "channel_url": "https://youtube.com" + video_details.get("authorUrl", ""),
        "youtube_video_link": "https://youtube.com/watch?v="
        + video_details.get("videoId"),
    }


def pick_video_url_fallback(video_details):
    streams = video_details.get("formatStreams", [])
    if not streams:
        return None

    def match(stream, resolution=None, container=None, encoding=None):
        return (
            (resolution is None or stream.get("resolution") == resolution)
            and (container is None or stream.get("container") == container)
            and (encoding is None or stream.get("encoding") == encoding)
        )

    # Priority 1
    for s in streams:
        if match(s, "480p", "mp4", "h264"):
            return s.get("url")

    # Priority 2
    for s in streams:
        if match(s, "360p", "mp4", "h264"):
            return s.get("url")

    # Priority 3
    for s in streams:
        if match(s, "480p"):
            return s.get("url")

    # Priority 4
    for s in streams:
        if match(s, "360p"):
            return s.get("url")

    return None
