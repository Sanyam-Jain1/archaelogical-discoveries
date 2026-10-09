"""Retries for remote cloud-optimised GeoTIFF access.

Long scans make thousands of HTTP range requests; an occasional dropped
connection or spurious error from a proxy should cost a retry, not the run.
"""

from __future__ import annotations

import logging
import os
import time

import rasterio
from rasterio.errors import RasterioError

log = logging.getLogger("moundfinder")

# Let GDAL retry individual HTTP range requests itself (any status code: some
# proxies answer a transient failure with a 404).
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")
os.environ.setdefault("GDAL_HTTP_RETRY_CODES", "ALL")


def retry(fn, tries: int = 4, what: str = "remote read", on_error=None):
    for attempt in range(tries):
        try:
            return fn()
        except (RasterioError, OSError) as e:
            if attempt == tries - 1:
                raise
            if on_error:
                on_error()
            log.info("%s failed (%s), retrying", what, str(e)[:120])
            time.sleep(2 ** (attempt + 1))


def open_remote(path: str, tries: int = 4):
    return retry(lambda: rasterio.open(path), tries, f"open {path}")
