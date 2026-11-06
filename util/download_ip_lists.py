"""Download the X4BNet datacenter/VPN IP lists used by kindler.abuse.

Usage: python util/download_ip_lists.py [DEST_DIR]   (default: kindler/data)
Exits non-zero if a download fails or a file is implausibly small.
"""

import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/datacenter/"
FILES = ("ipv4", "ipv6")
MIN_SIZE_BYTES = 50_000


def main():
    default_dest = Path(__file__).resolve().parent.parent / "kindler" / "data"
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dest
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / f"datacenter_{name}.txt"
        urllib.request.urlretrieve(f"{BASE_URL}{name}.txt", target)
        size = target.stat().st_size
        if size < MIN_SIZE_BYTES:
            sys.exit(f"{target.name} is too small ({size} bytes)")
        print(f"Downloaded {target} ({size} bytes)")


if __name__ == "__main__":
    main()
