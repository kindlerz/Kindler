import requests
from flask import render_template, Blueprint, request, Response

youtube_bp = Blueprint("youtube", __name__, url_prefix="/youtube")


@youtube_bp.route("/")
def home():
    return render_template("index_youtube.html")


@youtube_bp.route("/search")
def search():
    query = request.args.get("q")

    results = parse_search_result(search_youtube(query))

    return render_template("result_youtube.html", query=query, results=results)


INVIDIOUS_SEARCH_URL = "https://inv.thepixora.com/api/v1"


def search_youtube(query: str):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(
        f"{INVIDIOUS_SEARCH_URL}/search",
        params={"q": query},
        headers=headers,
        timeout=5,
    )
    return response.json()


def parse_search_result(search_result):
    result = []
    for item in search_result:
        if item.get("type") != "video":
            continue
        video_id = item.get("videoId")
        author = item.get("author")
        title = item.get("title")
        channel_url = "https://youtube.com" + item.get("authorUrl", "")
        channel_name = item.get("author")
        description = item.get("description")
        view_count = item.get("viewCountText")
        published_year = item.get("publishedText")

        # Find thumbnail: prefer "medium", fallback to "default"
        thumb_url = None
        thumbnails = item.get("videoThumbnails", [])

        for t in thumbnails:
            if t.get("quality") == "medium":
                thumb_url = t.get("url")
                break

        if not thumb_url:
            for t in thumbnails:
                if t.get("quality") == "default":
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
            }
        )
    return result


@youtube_bp.route("/readability")
def readability_page():
    query = request.args.get("q")
    video_id = request.args.get("id")
    video = get_video(get_youtube_video(video_id))
    return render_template("play_youtube.html", query=query, video=video)


@youtube_bp.route("/proxy_youtube")
def proxy_youtube():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }
    video_url = request.args.get("url")
    if not video_url:
        return "Missing url", 400
    r = requests.get(url=video_url, headers=headers)
    return Response(r.content, content_type=r.headers.get("Content-Type", "video/mp4"))


def get_youtube_video(video_id: str):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(
        f"{INVIDIOUS_SEARCH_URL}/videos/{video_id}",
        headers=headers,
        timeout=30,
    )
    return response.json()


def get_video(video_details):
    video_play_url = pick_video_url(video_details)
    return {
        "video_play_url": video_play_url,
        "description": video_details.get("descriptionHtml"),
        "title": video_details.get("title"),
        "published_text": video_details.get("publishedText"),
        "view_count": format_views(video_details.get("viewCount")),
        "channel_name": video_details.get("author"),
        "subscriber_count": video_details.get("subCountText"),
        "channel_url": "https://youtube.com" + video_details.get("authorUrl", ""),
        "youtube_video_link": "https://youtube.com/watch?v="
        + video_details.get("videoId"),
    }


def format_views(n):
    n = int(n)

    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B".rstrip("0").rstrip(".")
    elif n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K".rstrip("0").rstrip(".")
    else:
        return str(n)


def pick_video_url(video_details):
    """
    Selects the best video URL from formatStreams based on priority:
    1. 480p + mp4 + h264
    2. 360p + mp4 + h264
    3. any 480p
    4. any 360p
    5. else return None
    """

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
