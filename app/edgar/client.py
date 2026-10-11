"""HTTP client for SEC EDGAR — the polite way to talk to the SEC.

SEC rules we MUST respect (roadmap §3):
  - max 10 requests/second => at least 100 ms between two requests;
  - User-Agent must contain a real name + email (set in `.env`,
    read via app.config.settings.sec_user_agent);
  - cache responses instead of re-querying EDGAR on every user visit.

This module implements the rate limit + User-Agent. The file cache
(settings.cache_dir) and the bulk ZIP downloads are phase 1 TODOs.
"""

import time
import unicodedata

import httpx

from app.config import settings

# 10 requests/second == one request every 1/10 s == 0.1 s minimum gap.
MIN_INTERVAL = 0.1


class EdgarClient:
    def __init__(self):
        # Timestamp (monotonic) of the previous request; used by get() to
        # compute how long we still have to wait. 0.0 = "never called yet".
        self._last = 0.0

        # httpx.Client reuses one TCP connection across requests (faster than
        # creating a client per call) and carries the mandatory User-Agent on
        # every request automatically.
        #
        # BUGFIX: httpx encodes header values as ASCII and raised
        # UnicodeEncodeError on "Prénom" (é). HTTP header values are ASCII in
        # practice (RFC 7230); transliterate instead of failing — the SEC
        # only needs an identifiable name + email, accents are optional.
        user_agent = (
            unicodedata.normalize("NFKD", settings.sec_user_agent)
            .encode("ascii", "ignore")
            .decode()
        )
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=30,  # seconds; EDGAR can be slow, but never hang forever
        )

    def get(self, url: str) -> bytes:
        """GET `url`, respecting the 10 req/s budget, return raw bytes.

        Synchronous on purpose: bulk downloads run in jobs/nightly.py, where
        a simple sleep-loop is easier to reason about than asyncio.
        """
        # How much of the 0.1 s gap is still missing since the last request?
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

        # BUGFIX: was `time.monotonic` (no parentheses) — that stores the
        # FUNCTION itself, so the next call crashed with
        # `TypeError: unsupported operand type(s) for -: 'float' and 'function'`.
        self._last = time.monotonic()

        # raise_for_status(): a 4xx/5xx (e.g. 403 when the SEC bans us for a
        # bad User-Agent, 404 for a wrong CIK) must crash loudly, not be
        # silently cached as if it were data.
        resp = self._http.get(url)
        resp.raise_for_status()
        return resp.content

# TODO(phase 1): file cache keyed by URL under settings.cache_dir so a job
# restart (or a second pass) does not re-hit EDGAR at all.
