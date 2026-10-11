import base64, re

path = "scripts/researcher_adapter.py"
with open(path) as f:
    src = f.read()

NEW_HELPER = '''def _collect_source_urls(researcher) -> list[str]:
    """Kumpulkan URL sumber dari DUA tempat, urut, tanpa duplikat.

    `get_source_urls()` hanya berisi URL yang benar-benar di-scrape. Retriever yang
    mengembalikan konten penuh (SearXNG, PubMed Central) mengisi `research_sources`
    lewat jalur prefetched, jadi URL-nya TIDAK pernah masuk `visited_urls` dan
    laporan kehilangan sumber nyata (model lalu mengarang `example.com`). Di sini
    kita gabungkan keduanya.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for u in (researcher.get_source_urls() or []):
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    for src in (researcher.get_research_sources() or []):
        u = src.get("url") or src.get("href")
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


'''

marker = "def real_result(query: str, kind: str, value: str) -> dict:"
assert marker in src, "real_result marker missing"
src = src.replace(marker, NEW_HELPER + marker, 1)

old_call = 'return answer or "", list(researcher.get_source_urls() or [])'
n = src.count(old_call)
assert n == 2, f"expected 2 calls, found {n}"
src = src.replace(old_call, 'return answer or "", _collect_source_urls(researcher)')

with open(path, "w") as f:
    f.write(src)

import ast
ast.parse(src)
print("SYNTAX OK")
print("helper defined:", "def _collect_source_urls" in src)
print("helper used:", src.count("_collect_source_urls(researcher)"), "times")
