"""HTTP client for downloading regulator documents, with TLS verification always on.

Some government servers send only their own certificate and leave out the intermediate CA
(e.g. www.ocs.go.th, GlobalSign GCC R46 OV TLS CA 2025). Browsers and Windows fetch the missing
certificate themselves; Python on Linux does not, so downloads fail with "unable to get local
issuer certificate". Instead of turning verification off, the missing *intermediate* certificates
are shipped in ``config/ca/``: chains are still verified up to a root CA in the standard bundle.
Each file there is a public CA certificate taken from the issuer's AIA URL and checked against
its root (see config/ca/README.md).
"""

from __future__ import annotations

import ssl
from functools import lru_cache

import certifi
import httpx

from ..config import ROOT

USER_AGENT = "Mozilla/5.0 (compliance-copilot corpus fetcher; +https://github.com/)"


@lru_cache(maxsize=1)
def tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    for pem in sorted((ROOT / "config" / "ca").glob("*.pem")):
        ctx.load_verify_locations(cafile=str(pem))
    return ctx


def client(timeout: float = 120) -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=timeout, verify=tls_context(),
                        headers={"User-Agent": USER_AGENT})
