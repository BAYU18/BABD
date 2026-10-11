import time
import threading

# Global lock + pacing: gpt-researcher fires every sub-query through
# asyncio.gather, so 4 requests hit DuckDuckGo/Bing at the same instant and
# ddgs raises DDGSException("No results found.") for most of them. A module
# level lock serializes ALL searches across threads, and a minimum gap between
# consecutive searches keeps us under the rate limit.
_DDG_LOCK = threading.Lock()
_LAST_SEARCH_AT = 0.0
_MIN_GAP_SEC = 2.0


class Duckduckgo:
    """DuckDuckGo API Retriever (BABD-hardened).

    1. `region="wt-wt"` removed - ddgs>=9.16 built a Wikipedia-opensearch URL at
       wt.wikipedia.org (NXDOMAIN), so every search returned 0 sources.
    2. Accepts **kwargs - this gpt-researcher build instantiates retrievers with
       extra plumbing kwargs (headers, websocket, researcher=...); the upstream
       __init__ only took (query, query_domains), raising TypeError that
       Researcher._search swallowed into [].
    3. Globally serialized + paced - asyncio.gather fires every sub-query at
       once; the lock and minimum gap stop the burst that made ddgs return
       "No results found." for most concurrent queries.
    """
    def __init__(self, query, query_domains=None, **kwargs):
        from ..utils import check_pkg
        check_pkg("ddgs")
        from ddgs import DDGS
        self.ddg = DDGS()
        self.query = query
        self.query_domains = query_domains or None

    def search(self, max_results=5):
        global _LAST_SEARCH_AT
        last_error = None
        for attempt in range(5):
            with _DDG_LOCK:
                gap = time.monotonic() - _LAST_SEARCH_AT
                if gap < _MIN_GAP_SEC:
                    time.sleep(_MIN_GAP_SEC - gap)
                try:
                    search_response = self.ddg.text(self.query, max_results=max_results)
                    _LAST_SEARCH_AT = time.monotonic()
                    if search_response:
                        return search_response
                    last_error = "empty response"
                except Exception as e:
                    _LAST_SEARCH_AT = time.monotonic()
                    last_error = e
            time.sleep(2.0 * (attempt + 1))
        print(f"Error: {last_error}. Failed fetching sources. Resulting in empty response.")
        return []
