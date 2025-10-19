import os

GUTENDEX_SELF_HOST_URL = os.getenv(
    "GUTENDEX_SELF_HOST_URL", "http://gutendex:9193/books/"
)
GUTENDEX_THIRD_PARTY_URL = os.getenv(
    "GUTENDEX_THIRD_PARTY_URL", "https://gutendex.com/books/"
)
META_SEARCH_URL = os.getenv("META_SEARCH_URL", "http://localhost:8080/v1/books")
