"""Task documents: a main task given as a Markdown (or text) file, an upload, or a link.

    doc = from_file("specs/login.md")                 # a file on this machine
    doc = from_upload("login.md", text)               # sent from the dashboard
    doc = from_url("https://github.com/o/r/blob/main/spec.md")   # a link (GitHub/GitLab pages -> raw)

A document becomes the task's brief: its title (first heading) names the task, and its full text goes
to every agent of the run under "Task document". Only text formats are read; nothing is executed.
"""
import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 500_000          # per document: it is sent to every agent of the run
TEXT_EXTENSIONS = (".md", ".markdown", ".mdown", ".txt", ".text", ".rst")
FETCH_TIMEOUT = 20
MAX_REDIRECTS = 5
# Links may only reach public internet addresses: never this machine, the local network or a cloud
# metadata service (a link sent over Telegram must not read internal services). Set
# BABD_ALLOW_PRIVATE_LINKS=1 to read documents from your own network.
ALLOW_PRIVATE_ENV = "BABD_ALLOW_PRIVATE_LINKS"


class TaskDocError(Exception):
    pass


def make(name, text, source, url=None):
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise TaskDocError(f"{name}: the document is empty")
    if len(text.encode()) > MAX_BYTES:
        raise TaskDocError(f"{name}: the document is larger than {MAX_BYTES // 1000} KB")
    doc = {"name": name, "source": source, "title": title_of(text, name), "text": text, "chars": len(text)}
    if url:
        doc["url"] = url
    return doc


def title_of(text, fallback=""):
    """The first Markdown heading (or front-matter title), else the first line, at most 120 characters."""
    fm = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if fm:
        m = re.search(r"^title:\s*['\"]?(.+?)['\"]?\s*$", fm.group(1), re.M)
        if m:
            return m.group(1)[:120]
        text = text[fm.end():]
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^#{1,6}\s+(.*)", line)
        title = (m.group(1) if m else line).strip(" #*_`")
        if title:
            return title[:120]
    return os.path.splitext(os.path.basename(fallback))[0][:120] or "Task"


def _decode(raw, name):
    if b"\x00" in raw[:4096] and raw[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise TaskDocError(f"{name}: not a text file (send a .md or .txt file)")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def from_file(path):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise TaskDocError(f"{path}: no such file")
    if os.path.getsize(path) > MAX_BYTES:
        raise TaskDocError(f"{path}: the document is larger than {MAX_BYTES // 1000} KB")
    with open(path, "rb") as f:
        return make(os.path.basename(path), _decode(f.read(), path), "file")


def from_upload(name, text):
    name = os.path.basename(str(name or "task.md"))[:120] or "task.md"
    if not name.lower().endswith(TEXT_EXTENSIONS):
        raise TaskDocError(f"{name}: send a Markdown or text file ({', '.join(TEXT_EXTENSIONS)})")
    if not isinstance(text, str):
        raise TaskDocError(f"{name}: the content must be text")
    return make(name, text, "upload")


def raw_url(url):
    """The raw-file address for links to a file page on GitHub, GitLab or a Gist."""
    u = urllib.parse.urlparse(url)
    parts = u.path.strip("/").split("/")
    if u.netloc in ("github.com", "www.github.com") and len(parts) > 4 and parts[2] in ("blob", "raw"):
        return f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{'/'.join(parts[3:])}"
    if u.netloc == "gist.github.com" and len(parts) >= 2 and "raw" not in parts:
        return f"https://gist.githubusercontent.com/{parts[0]}/{parts[1]}/raw"
    if "/-/blob/" in u.path:  # GitLab (gitlab.com or self-hosted)
        return urllib.parse.urlunparse(u._replace(path=u.path.replace("/-/blob/", "/-/raw/", 1)))
    return url


def check_public(url, resolve=None):
    """Raise TaskDocError unless `url` is http(s) and its host resolves only to public addresses."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise TaskDocError(f"{url or 'link'}: only http(s) links can be read")
    if u.username or u.password:
        raise TaskDocError(f"{u.hostname}: links with a user name or password are not read")
    if os.environ.get(ALLOW_PRIVATE_ENV) == "1":
        return
    try:
        infos = (resolve or socket.getaddrinfo)(u.hostname, u.port or (443 if u.scheme == "https" else 80),
                                                 type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise TaskDocError(f"{u.hostname}: cannot resolve the address ({e})") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise TaskDocError(f"{u.hostname}: {ip} is a private or local address; only public links are read "
                               f"(set {ALLOW_PRIVATE_ENV}=1 to allow your own network)")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another public http(s) address, at most MAX_REDIRECTS times."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_safe_opener = urllib.request.build_opener(_CheckedRedirects)
_CheckedRedirects.max_redirections = MAX_REDIRECTS


def from_url(url, opener=None):
    url = (url or "").strip()
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise TaskDocError(f"{url or 'link'}: only http(s) links can be read")
    fetch = raw_url(url)
    if opener is None:
        check_public(fetch)
    req = urllib.request.Request(fetch, headers={"User-Agent": "babd-taskdocs/1", "Accept": "text/markdown, text/plain, */*"})
    try:
        with (opener or _safe_opener.open)(req, timeout=FETCH_TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise TaskDocError(f"{url}: HTTP {e.code} (is the link public?)") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TaskDocError(f"{url}: could not download ({getattr(e, 'reason', e)})") from e
    if len(raw) > MAX_BYTES:
        raise TaskDocError(f"{url}: the document is larger than {MAX_BYTES // 1000} KB")
    if "html" in ctype and not u.path.lower().endswith(TEXT_EXTENSIONS):
        raise TaskDocError(f"{url}: this is a web page, not a Markdown file (link the raw .md file)")
    name = os.path.basename(u.path) or u.netloc
    return make(name, _decode(raw, url), "link", url=url)


def brief_of(docs):
    """The text every agent gets for the task's documents."""
    out = []
    for d in docs:
        where = d.get("url") or d["name"]
        out.append(f"## Task document: {d['name']} ({where})\n\n{d['text']}")
    return "\n\n".join(out)


def summary(doc):
    """A document without its text, for lists and run state."""
    return {k: doc[k] for k in ("name", "source", "title", "chars", "url") if k in doc}
