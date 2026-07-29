from enum import Enum, auto

import requests

from kindler.config import META_SEARCH_URL


class Provider(Enum):
    STANDARD_EBOOKS = "STANDARD_EBOOKS"
    GUTENBERG = "GUTENBERG"
    GUTENBERG_AUSTRALIA = "GUTENBERG_AUSTRALIA"


def search_book_by_provider(provider: Provider, query: str):
    response = requests.get(
        f"{META_SEARCH_URL}/search",
        params={"q": query, "provider": provider.value},
        timeout=5,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected metasearch response: {data!r}")
    return data


def get_book_details(book_id):
    response = requests.get(f"{META_SEARCH_URL}/{book_id}", timeout=5)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected metasearch response: {data!r}")
    return data
