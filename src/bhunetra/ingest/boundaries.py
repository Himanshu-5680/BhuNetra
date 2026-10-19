"""District boundaries (geoBoundaries IND ADM2, gbOpen). Large file is stored in Git-LFS upstream."""
from __future__ import annotations

from bhunetra.net import Fetched, fetch_to_bronze

# Raw GitHub path returns an LFS pointer; the /media/ host serves the real file.
URL = ("https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/"
       "releaseData/gbOpen/IND/ADM2/geoBoundaries-IND-ADM2_simplified.geojson")


URL_ADM1 = URL.replace("ADM2", "ADM1")


def ingest_boundaries(level: str = "ADM2", **kw) -> Fetched:
    url, src = (URL, "geoboundaries_ind_adm2") if level == "ADM2" else (URL_ADM1, "geoboundaries_ind_adm1")
    f = fetch_to_bronze(src, url, ext="geojson", **kw)
    head = f.path.read_bytes()[:200]
    if head.startswith(b"version https://git-lfs"):  # got a pointer, not data: fail loudly
        raise RuntimeError("Got a Git-LFS pointer instead of GeoJSON. Check the URL.")
    return f
