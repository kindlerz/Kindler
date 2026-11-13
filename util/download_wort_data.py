"""Download the wort dictionary data (wort.dat, wort.idx, wort-en.idx) used by kindler.api.dictionary.

Usage: python util/download_wort_data.py VERSION [DEST_DIR]   (default: kindler/data/wort)
The files come from the wort release tarball at github.com/kasramp/wort.
Exits non-zero if the download fails or a file is missing or implausibly small.
"""

import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

URL = "https://github.com/kasramp/wort/releases/download/{v}/wort-{v}-unix.tar.gz"
FILES = ("wort.dat", "wort.idx", "wort-en.idx")
MIN_SIZE_BYTES = 1_000_000


def main():
    version = sys.argv[1]
    default_dest = Path(__file__).resolve().parent.parent / "kindler" / "data" / "wort"
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else default_dest
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as tmp:
        with urllib.request.urlopen(URL.format(v=version), timeout=60) as response:
            while chunk := response.read(1 << 20):
                tmp.write(chunk)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
            for name in FILES:
                member = tar.getmember(f"wort-{version}-unix/build/data/{name}")
                with tar.extractfile(member) as src, open(dest / name, "wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
                size = (dest / name).stat().st_size
                if size < MIN_SIZE_BYTES:
                    sys.exit(f"{name} is too small ({size} bytes)")
                print(f"Extracted {dest / name} ({size} bytes)")


if __name__ == "__main__":
    main()
