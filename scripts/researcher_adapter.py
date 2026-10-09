#!/usr/bin/env python3
"""Adapter lokal gpt-researcher untuk agent BABD "researcher".

Dipakai oleh harness `process` di agents.json: BABD menulis prompt ke stdin
(system prompt persona + "\\n\\n---\\n\\n" + task) dan membaca stdout program ini.

Kontrak (dipakai oleh tests/test_researcher.py):
  stdin   : prompt lengkap dari BABD
  stdout  : satu blok JSON {"query", "answer", "sources": [{"title", "url"}], "local"}
            lalu "\\n---\\n" dan ringkasan teks yang enak dibaca
  exit 0  : riset berhasil
  exit 2  : tidak ada search provider / library research belum siap
            (jujur gagal, TIDAK PERNAH mengarang sumber)
  exit 3  : error lain (prompt kosong)

Semua berjalan lokal: gpt-researcher dipakai sebagai library dari hasil
scripts/researcher_setup.sh; LLM diambil dari env BABD_LLM_* yang disediakan
babd/harness/routing.py. Tidak ada service jaringan yang harus dijaga hidup.

Penting: BABD memanggil skrip ini dengan `python scripts/researcher_adapter.py`,
sedangkan gpt-researcher dipasang di venv terpisah (.babd/researcher/venv).
Jadi `import gpt_researcher` TIDAK akan pernah ditemukan di interpreter itu.
Skrip ini mengeksekusi ulang dirinya dengan interpreter venv tersebut
(lihat interpreter() / reexec_if_needed()).

Env:
  RESEARCHER_PROVIDER           searxng | duckduckgo | tavily (opsional; mengalahkan default)
  RESEARCHER_SEARXNG_URL        URL SearXNG lokal (provider utama bila diisi)
  RESEARCHER_ALLOW_DUCKDUCKGO   "1" = boleh pakai DuckDuckGo tanpa key
  RESEARCHER_FAKE               "1" = jawaban sintetis, hanya untuk test
  RESEARCHER_MAX_RESULTS        jumlah sumber maksimum (default 6)
  RESEARCHER_HOME               lokasi vendor+venv (default <root>/.babd/researcher)
  RESEARCHER_PROMPT             internal: prompt yang dibawa melewati re-exec venv
                                (diisi otomatis oleh reexec_if_needed; jangan diisi manual)
  BABD_LLM_BASE_URL/MODEL/API_KEY  LLM yang dipakai gpt-researcher
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SEPARATOR = "\n\n---\n\n"
EXIT_OK, EXIT_NO_PROVIDER, EXIT_ERROR = 0, 2, 3
MARKER = "RESEARCHER_REEXEC"  # penanda agar re-exec tidak pernah berulang
PROMPT_ENV = "RESEARCHER_PROMPT"  # prompt dibawa melewati os.execve (stdin sudah habis dibaca)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.environ.get("RESEARCHER_HOME") or os.path.join(ROOT, ".babd", "researcher")
VENV_PYTHON = os.path.join(HOME, "venv", "bin", "python")


def log(msg: str) -> None:
    print(f"researcher: {msg}", file=sys.stderr)


def has_gpt_researcher(interpreter: str) -> bool:
    """Benar bila `interpreter` bisa meng-import gpt_researcher (tanpa menjalankan riset)."""
    import subprocess
    try:
        proc = subprocess.run([interpreter, "-c", "import gpt_researcher"],
                              capture_output=True, text=True, timeout=60)
    except OSError:
        return False
    return proc.returncode == 0


def interpreter() -> str:
    """Interpreter yang akan menjalankan riset: venv vendor bila ada, selain itu yang sekarang."""
    if not os.path.exists(VENV_PYTHON):
        return sys.executable
    # Bandingkan sys.prefix, BUKAN realpath: di mesin ini venv/bin/python dan interpreter BABD
    # sama-sama symlink ke /usr/bin/python3.12, jadi realpath menyamakannya padahal venv-lah yang
    # punya gpt_researcher di site-packages-nya.
    venv_prefix = os.path.dirname(os.path.dirname(VENV_PYTHON))
    if os.path.realpath(sys.prefix) == os.path.realpath(venv_prefix):
        return sys.executable          # kita sudah berjalan di dalam venv itu
    return VENV_PYTHON


def reexec_if_needed(argv: list[str], prompt: str = "") -> None:
    """Jalankan ulang skrip ini dengan interpreter venv supaya `import gpt_researcher` berhasil.

    `os.execve` mengganti citra proses; stdin yang sudah dikonsumsi `sys.stdin.read()`
    TIDAK ikut kembali. Jadi prompt kita titipkan lewat env (PROMPT_ENV) supaya proses baru
    membacanya dari sana, bukan dari stdin yang sudah habis - inilah bug rc=3
    "no question in the prompt (stdin was empty)".
    """
    target = interpreter()
    if target == sys.executable or os.environ.get(MARKER):
        return
    env = dict(os.environ, **{MARKER: "1"})
    if prompt:
        env[PROMPT_ENV] = prompt
    os.execve(target, [target, os.path.abspath(__file__), *argv], env)


def extract_query(prompt: str) -> str:
    """Ambil bagian setelah pemisah terakhir: itu task-nya, bukan system prompt persona."""
    text = (prompt or "").strip()
    if not text:
        return ""
    parts = re.split(r"\n-{3,}\n", text)
    return parts[-1].strip()


def search_provider() -> tuple[str, str]:
    """(kind, value) provider pencarian. kind "" = tidak ada.

    `RESEARCHER_PROVIDER` eksplisit (kontrak DevOps) mengalahkan deteksi otomatis, supaya
    operator bisa mematikan sebuah provider hanya dengan mengubah satu variabel.
    """
    explicit = (os.environ.get("RESEARCHER_PROVIDER") or "").strip().lower()
    searxng = (os.environ.get("RESEARCHER_SEARXNG_URL") or "").strip()
    duck = (os.environ.get("RESEARCHER_ALLOW_DUCKDUCKGO") or "").strip().lower() in ("1", "true", "yes")
    tavily = bool((os.environ.get("TAVILY_API_KEY") or "").strip())
    if explicit in ("searxng", "searxng-lokal", "searx"):
        return ("searxng", searxng) if searxng else ("", "")
    if explicit in ("duckduckgo", "ddg"):
        return ("duckduckgo", "duckduckgo")
    if explicit == "tavily":
        return ("tavily", "tavily") if tavily else ("", "")
    if searxng:
        return "searxng", searxng
    if duck:
        return "duckduckgo", "duckduckgo"
    if tavily:
        return "tavily", "tavily"
    return "", ""


def max_results() -> int:
    try:
        return max(1, min(20, int(os.environ.get("RESEARCHER_MAX_RESULTS") or 6)))
    except ValueError:
        return 6


def fake_result(query: str) -> dict:
    """Jawaban sintetis untuk test. Jelas-jelas bukan temuan nyata."""
    return {"query": query,
            "answer": f"[RESEARCHER_FAKE] jawaban sintetis untuk: {query}",
            "sources": [{"title": "fake source", "url": "https://example.invalid/fake"}],
            "local": True}


# RETRIEVER gpt-researcher -> (nama env yang dibaca library, nilai env kita)
RETRIEVER_ENV = {"searxng": ("SEARX_URL", "RETRIEVER"),
                 "duckduckgo": (None, "RETRIEVER"),
                 "tavily": ("TAVILY_API_KEY", "RETRIEVER")}
RETRIEVER_NAME = {"searxng": "searx", "duckduckgo": "duckduckgo", "tavily": "tavily"}


def real_result(query: str, kind: str, value: str) -> dict:
    """Panggil gpt-researcher sebagai library lokal. Raise RuntimeError bila tidak bisa.

    gpt-researcher 0.15.x punya API async (conduct_research/write_report adalah coroutine,
    get_source_urls sinkron). Diverifikasi terhadap versi yang di-vendor oleh
    scripts/researcher_setup.sh pada 2026-10-09.
    """
    try:
        from gpt_researcher import GPTResearcher  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "gpt-researcher is not installed for this adapter. Run scripts/researcher_setup.sh "
            f"(offline: the adapter cannot search without the library). ({e})") from e

    import asyncio

    os.environ.setdefault("RETRIEVER", RETRIEVER_NAME[kind])
    os.environ["RETRIEVER"] = RETRIEVER_NAME[kind]     # provider eksplisit selalu menang
    if kind == "searxng":
        os.environ["SEARX_URL"] = value
    # gpt-researcher memakai klien OpenAI-compatible: teruskan LLM tim dari BABD_* ke OPENAI_*.
    for src, dst in (("BABD_LLM_API_KEY", "OPENAI_API_KEY"), ("BABD_LLM_BASE_URL", "OPENAI_BASE_URL"),
                     ("BABD_LLM_MODEL", "FAST_LLM"), ("BABD_LLM_MODEL", "SMART_LLM")):
        if os.environ.get(src) and not os.environ.get(dst):
            os.environ[dst] = os.environ[src]

    async def run() -> tuple[str, list[str]]:
        researcher = GPTResearcher(query=query, report_type="research_report")
        await researcher.conduct_research()
        answer = await researcher.write_report()
        return answer or "", list(researcher.get_source_urls() or [])

    try:
        answer, urls = asyncio.run(run())
    except Exception as e:  # noqa: BLE001 - jadikan kegagalan yang jujur, bukan sumber palsu
        raise RuntimeError(f"gpt-researcher failed: {type(e).__name__}: {e}") from e

    sources = [{"title": u, "url": u} for u in urls[:max_results()]]
    return {"query": query, "answer": answer.strip(), "sources": sources, "local": True}


def render_text(data: dict) -> str:
    lines = [f"Riset lokal untuk: {data['query']}", "", data.get("answer") or "(tidak ada jawaban)"]
    sources = data.get("sources") or []
    lines += ["", "Sumber:"]
    lines += [f"- {s.get('title')} <{s.get('url')}>" for s in sources] or ["- (tidak ada sumber)"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local gpt-researcher adapter for the BABD researcher agent.")
    ap.add_argument("--json", action="store_true", help="print the JSON block before the text summary")
    ap.add_argument("--which-python", action="store_true",
                    help="print the interpreter that runs the research, then exit (diagnostics)")
    args = ap.parse_args(argv)

    if args.which_python:
        print(interpreter())
        return EXIT_OK

    # Proses hasil re-exec mewarisi stdin yang sudah habis, jadi prompt diambil dari env
    # (dititipkan reexec_if_needed). Jalur normal tetap membaca stdin dari harness.
    raw_prompt = os.environ.get(PROMPT_ENV, "")
    if not raw_prompt:
        raw_prompt = sys.stdin.read()
    query = extract_query(raw_prompt)
    if not query:
        log("no question in the prompt (stdin was empty)")
        return EXIT_ERROR

    if (os.environ.get("RESEARCHER_FAKE") or "").strip() in ("1", "true", "yes"):
        data = fake_result(query)
    else:
        reexec_if_needed([a for a in (argv if argv is not None else sys.argv[1:])], raw_prompt)
        kind, value = search_provider()
        if not kind:
            log("no search provider: set RESEARCHER_SEARXNG_URL to a local SearXNG, or "
                "RESEARCHER_ALLOW_DUCKDUCKGO=1. Refusing to invent sources.")
            return EXIT_NO_PROVIDER
        try:
            data = real_result(query, kind, value)
        except RuntimeError as e:
            log(str(e))
            return EXIT_NO_PROVIDER

    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        print("---")
    sys.stdout.write(render_text(data))
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_ERROR)
