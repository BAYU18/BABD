"""Pull requests on GitHub for a project with `"merge": "pr"`.

When a task ends well, BABD pushes the task's branch (babd/<task id>) and opens a pull request into the
project's branch, with the report as its description. The dashboard then follows the PR's CI checks;
the PR is merged when you press Merge (dashboard, Telegram) and the checks are green, or by itself
when the project says `"pr_merge": "auto"`.

The token is a GitHub token with "contents" and "pull requests" write access, kept in .env under
`project.github_token_env` (default GITHUB_TOKEN). It is given to git through the environment, never on
a command line. `github_api` points to GitHub Enterprise (https://ghe.example.com/api/v3).
"""
import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

API = "https://api.github.com"
REMOTE_RE = re.compile(r"^(?:https?://(?:[^@/]+@)?([^/]+)/|git@([^:]+):|ssh://git@([^/]+)/)([^/]+)/(.+?)(?:\.git)?/?$")


class GitHubError(Exception):
    pass


def parse_remote(url):
    """(host, owner, repo) of a GitHub remote URL, or None."""
    m = REMOTE_RE.match((url or "").strip())
    if not m:
        return None
    return (m.group(1) or m.group(2) or m.group(3)), m.group(4), m.group(5)


def token_of(project_cfg):
    return os.environ.get((project_cfg or {}).get("github_token_env") or "GITHUB_TOKEN") or None


class GitHub:
    def __init__(self, token, api=None):
        self.token = token
        self.api = (api or API).rstrip("/")

    def call(self, method, path, body=None, timeout=30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.api}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "babd", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("message", "")
            except ValueError:
                msg = ""
            raise GitHubError(f"GitHub {method} {path.split('?')[0]}: HTTP {e.code} {msg}".strip()) from e
        except (urllib.error.URLError, OSError) as e:
            raise GitHubError(f"GitHub: {getattr(e, 'reason', e)}") from e
        return json.loads(raw) if raw else {}

    def create_pr(self, owner, repo, head, base, title, body):
        return self.call("POST", f"/repos/{owner}/{repo}/pulls", {"title": title[:240], "head": head, "base": base,
                                                                  "body": body[:60000], "maintainer_can_modify": True})

    def pr(self, owner, repo, number):
        return self.call("GET", f"/repos/{owner}/{repo}/pulls/{number}")

    def checks(self, owner, repo, sha):
        """"success" / "failure" / "pending" / "none" for a commit (check runs and commit statuses)."""
        states = []
        runs = self.call("GET", f"/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100").get("check_runs") or []
        for r in runs:
            if r.get("status") != "completed":
                states.append("pending")
            else:
                states.append("success" if r.get("conclusion") in ("success", "neutral", "skipped") else "failure")
        st = self.call("GET", f"/repos/{owner}/{repo}/commits/{sha}/status")
        for s in st.get("statuses") or []:
            states.append({"success": "success", "pending": "pending"}.get(s.get("state"), "failure"))
        if not states:
            return "none"
        return "failure" if "failure" in states else "pending" if "pending" in states else "success"

    def merge(self, owner, repo, number, method="squash", title=None):
        body = {"merge_method": method}
        if title:
            body["commit_title"] = title[:240]
        return self.call("PUT", f"/repos/{owner}/{repo}/pulls/{number}/merge", body)


def push_env(token, host):
    """Env that gives git the token for this host (an HTTP header), without a command line or file."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}", "GIT_TERMINAL_PROMPT": "0"}


def push_branch(project_dir, branch, token=None, host=None, remote="origin", timeout=300):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_"))}
    if token and host:
        env.update(push_env(token, host))
    proc = subprocess.run(["git", "push", "-q", "-u", remote, f"{branch}:{branch}"], cwd=project_dir,
                          capture_output=True, text=True, env=env, timeout=timeout)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().replace(token or "\0", "***")
        raise GitHubError(f"git push failed: {msg[-300:]}")


def open_pr(project, ws, title, body, project_cfg, gh=None):
    """Push the task's branch and open its PR. Returns the PR record kept in the task's state."""
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=project["path"], capture_output=True,
                            text=True).stdout.strip()
    where = parse_remote(remote)
    if project.get("github_repo"):  # the remote is not a github.com URL (an SSH alias, a mirror)
        owner, repo = project["github_repo"].split("/", 1)
        where = (where[0] if where else "github.com", owner, repo)
    if not where or not remote:
        raise GitHubError("the project has no GitHub remote named origin (set its repo to a GitHub URL)")
    host, owner, repo = where
    token = token_of(project_cfg)
    if not token:
        raise GitHubError(f"no GitHub token: set {(project_cfg or {}).get('github_token_env') or 'GITHUB_TOKEN'} "
                          "(Team settings → GitHub token)")
    push_branch(project["path"], ws["branch"], token, host if remote.startswith("http") else None)
    gh = gh or GitHub(token, (project_cfg or {}).get("github_api"))
    pr = gh.create_pr(owner, repo, ws["branch"], ws["base"], title, body)
    return {"number": pr.get("number"), "url": pr.get("html_url"), "owner": owner, "repo": repo,
            "sha": (pr.get("head") or {}).get("sha"), "state": "open", "checks": "pending", "merged": False,
            "merge_requested": False}
