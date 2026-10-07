"""Command line for the AI development team.

  python -m babd check                         ping every agent through its harness and LLM
  python -m babd harnesses                     list the available harness types
  python -m babd use <agent> <harness> [--set key=value ...]
                                               select a harness: installs and configures it
  python -m babd setup [agent ...]             install + configure every agent's harness
  python -m babd dashboard [--port 8800]       web panel: configure, command and watch the agents
        [--public-url https://… --allow-ip … --trust-proxy]   for access from other machines
  python -m babd set-password                  password login for the dashboard
  python -m babd brain [words ...]             team memory (GBrain): status, or recall about some words
  python -m babd ask <agent> "message"         one message to one agent
  python -m babd chat <agent>                  interactive chat with one agent
  python -m babd run "goal" ["goal 2" ...] [--approve] [--update-dashboard]
                                               full team run: plan -> work -> CEO report; several
                                               goals run at the same time, sharing the agents.
                                               A goal can be a .md file or a link to one:
  python -m babd run specs/login.md https://github.com/o/r/blob/main/spec.md
  python -m babd run "Build what the spec says" --doc spec.md [--doc <link>]
  python -m babd report <run id> [-o report.md]   a task as a Markdown report
  python -m babd resume <run id> [--approve]  continue a failed / stopped / interrupted task from its
                                               last finished step
"""
import argparse
import json
import os
import re
import sys
import threading

from .config import ROOT, load_config, load_dotenv, save_config
from .gbrain import BrainError, GBrain, format_memory
from .harness import HARNESSES, create_harness, select_harness
from .llm import LLMError
from .team import Team, apply_run_to_config


def main(argv=None):
    load_dotenv()
    from .config import secure_dirs
    secure_dirs()
    p = argparse.ArgumentParser(prog="python -m babd", description="Run the AI development team.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="ping every agent through its harness and LLM")
    sub.add_parser("harnesses", help="list the available harness types")
    u = sub.add_parser("use", help="select a harness for an agent, then install and configure it")
    u.add_argument("agent")
    u.add_argument("harness", choices=sorted(HARNESSES))
    u.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help='harness option, e.g. --set max_turns=50 --set toolsets=\'["web","file"]\'')
    u.add_argument("--no-setup", action="store_true", help="only change agents.json")
    st = sub.add_parser("setup", help="install and configure the harness of every (or the named) agent")
    st.add_argument("agents", nargs="*")
    br = sub.add_parser("brain", help="the team's GBrain memory: status, or recall what it knows about some words")
    br.add_argument("words", nargs="*", help="words to recall (empty: show status)")
    db = sub.add_parser("dashboard", help="open the web panel to configure, command and watch the agents")
    db.add_argument("--host", default="127.0.0.1")
    db.add_argument("--port", type=int, default=8800)
    db.add_argument("--no-browser", action="store_true")
    db.add_argument("--public-url", help="the address people open, e.g. https://babd.example.com (behind a reverse proxy)")
    db.add_argument("--allow-ip", help="only these addresses / networks may connect, e.g. 203.0.113.7,10.0.0.0/8")
    db.add_argument("--trust-proxy", action="store_true",
                    help="behind a reverse proxy: client address from X-Forwarded-For, HTTPS from X-Forwarded-Proto")
    sub.add_parser("set-password", help="set the dashboard password (for access from other machines)")
    a = sub.add_parser("ask", help="send one message to one agent")
    a.add_argument("agent")
    a.add_argument("message")
    c = sub.add_parser("chat", help="interactive chat with one agent")
    c.add_argument("agent")
    r = sub.add_parser("run", help="full team run on a goal (several goals: run at the same time)")
    r.add_argument("goal", nargs="+", help="a goal, a .md/.txt file, or a link to one (each is a task)")
    r.add_argument("--mode", default="auto", choices=("auto", "quick", "full"),
                   help="auto: the Team Lead picks who is needed (default); quick: one agent, never the whole team; "
                        "full: always the whole flow")
    r.add_argument("--skip", default="", help="leave out for these tasks: architect, devops, prep (comma separated)")
    r.add_argument("--model", action="append", default=[], metavar="AGENT=MODEL",
                   help="use another model for one agent in these tasks, e.g. developer=qwen2.5-coder:7b")
    r.add_argument("--project", help="the project the agents work in (agents.json \"projects\"; default: default)")
    r.add_argument("--doc", action="append", default=[], metavar="FILE_OR_LINK",
                   help="a task document (Markdown file or link) for the goal; repeat for more")
    r.add_argument("--approve", action="store_true", help="approve the deploy without asking (CEO approval gate)")
    r.add_argument("--update-dashboard", action="store_true",
                   help="write the CEO report into agents.json and regenerate workspace.svg")
    rp = sub.add_parser("report", help="a finished task as a Markdown report")
    rp.add_argument("run_id")
    rp.add_argument("-o", "--output", help="write to this file (default: print)")
    rs = sub.add_parser("resume", help="continue a failed, stopped or interrupted task from its last finished step")
    rs.add_argument("run_id")
    rs.add_argument("--approve", action="store_true", help="approve the deploy without asking")
    args = p.parse_args(argv)

    if args.cmd == "harnesses":
        for kind, cls in HARNESSES.items():
            print(f"{kind:<15} {cls.label:<16} {(cls.__doc__ or '').strip().splitlines()[0]}")
        return 0

    if args.cmd == "dashboard":
        from .dashboard.server import serve
        try:
            serve(args.host, args.port, open_browser=not args.no_browser, public_url=args.public_url,
                  allow_ip=args.allow_ip, trust_proxy=args.trust_proxy)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0

    if args.cmd == "set-password":
        import getpass
        from .config import set_env_var
        from .dashboard.auth import HASH_ENV, hash_password
        pw = getpass.getpass("New dashboard password (10+ characters): ")
        if pw != getpass.getpass("Again: "):
            print("error: the two passwords differ", file=sys.stderr)
            return 2
        try:
            set_env_var(HASH_ENV, hash_password(pw))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"saved (as a PBKDF2 hash in .env, {HASH_ENV}); restart `babd dashboard` to use it")
        return 0

    cfg = load_config()
    agents = {a["id"]: a for a in cfg["agents"]}

    if args.cmd == "brain":
        brain = GBrain(cfg["project"])
        if not args.words:
            print(json.dumps(brain.status(), indent=2))
            return 0
        try:
            print(format_memory(brain.recall(" ".join(args.words))))
        except BrainError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    if args.cmd in ("use", "setup"):
        targets = [args.agent] if args.cmd == "use" else (args.agents or list(agents))
        unknown = [t for t in targets if t not in agents]
        if unknown:
            print(f"unknown agent {unknown[0]!r}; choose from: {', '.join(agents)}", file=sys.stderr)
            return 2
        if args.cmd == "use":
            overrides = {}
            for item in args.set:
                key, _, value = item.partition("=")
                try:
                    overrides[key] = json.loads(value)
                except json.JSONDecodeError:
                    overrides[key] = value
            new = select_harness(agents[args.agent], args.harness, overrides)
            save_config(cfg)
            print(f"{args.agent}: harness -> {json.dumps(new)}")
            sys.path.insert(0, ROOT)
            import generate_workspace
            generate_workspace.main()
            if args.no_setup:
                return 0
        failed = 0
        if args.cmd == "setup" or args.cmd == "use":
            try:
                print(f"OK   {'gbrain':<10} [team memory] {GBrain(cfg['project']).setup()}")
            except (BrainError, OSError) as e:
                failed += 1
                print(f"FAIL {'gbrain':<10} {e}")
        for agent_id in targets:
            try:
                h = create_harness(agents[agent_id], cfg["project"])
                print(f"OK   {agent_id:<10} [{h.type}] {h.setup()}")
            except LLMError as e:
                failed += 1
                print(f"FAIL {agent_id:<10} {e}")
        return 1 if failed else 0

    team = Team(cfg, log=lambda m: print(m, file=sys.stderr))

    if args.cmd == "check":
        ok_all = True
        for agent_id, (ok, msg) in team.check().items():
            ag = team.by_id[agent_id]
            llm = ag.cfg["llm"]
            print(f"{'OK  ' if ok else 'FAIL'} {ag.name:<12} [{ag.harness.type}] {llm['model']} @ "
                  f"{llm.get('base_url', '')}  {msg.strip()[:120]}")
            ok_all &= ok
        return 0 if ok_all else 1

    if args.cmd in ("ask", "chat"):
        agent = team.by_id.get(args.agent)
        if not agent:
            print(f"unknown agent {args.agent!r}; choose from: {', '.join(team.by_id)}", file=sys.stderr)
            return 2
        try:
            if args.cmd == "ask":
                print(agent.ask(args.message))
                return 0
            print(f"Chatting with {agent.name} ({agent.harness.label}, {agent.cfg['llm']['model']}). "
                  "Empty line or Ctrl-D to quit.")
            while True:
                try:
                    msg = input("you> ").strip()
                except EOFError:
                    break
                if not msg:
                    break
                print(f"{agent.id}> {agent.chat(msg)}\n")
            return 0
        except LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    if args.cmd == "run":
        return run_goals(args, cfg, team)

    if args.cmd == "report":
        from . import reports
        from .flow import RUNS_DIR
        d = os.path.join(RUNS_DIR, os.path.basename(args.run_id))
        if not os.path.exists(os.path.join(d, "state.json")):
            print(f"error: no run {args.run_id}", file=sys.stderr)
            return 2
        md = reports.markdown(*reports.load(d), names={a["id"]: a.get("short_name") or a["name"] for a in cfg["agents"]})
        if args.output:
            with open(args.output, "w") as f:
                f.write(md)
            print(f"wrote {args.output}")
        else:
            print(md)
        return 0

    if args.cmd == "resume":
        from .flow import FlowError, Run
        try:
            run = Run(team, "", approver=lambda r: (args.approve, "auto-approved (--approve)" if args.approve else
                                                    "no approval given (use --approve or the dashboard)"),
                      run_id=args.run_id, resume=True)
        except FlowError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        done = len(run.state["checkpoints"])
        print(f"resuming {run.id}: {run.goal} ({done} step(s) already done)", file=sys.stderr)
        state = run.execute()
        print(f"run {state['status']}" + (f": {state['error']}" if state.get("error") else ""))
        return 0 if state["status"] == "done" else 1


def read_doc(ref):
    from . import taskdocs
    if re.match(r"^https?://", ref.strip()):
        return taskdocs.from_url(ref)
    return taskdocs.from_file(ref)


def tasks_from_args(goals, doc_refs):
    """[(goal, docs)]: a file or link argument is its own task; --doc documents go with the text goal(s)."""
    from . import taskdocs
    tasks = []
    for g in goals:
        g = g.strip()
        if not g:
            continue
        looks_like_doc = re.match(r"^https?://\S+$", g) or (
            "\n" not in g and g.lower().endswith(taskdocs.TEXT_EXTENSIONS) and os.path.isfile(os.path.expanduser(g)))
        if looks_like_doc:
            doc = read_doc(g)
            tasks.append((doc["title"], [doc]))
        else:
            tasks.append((g, []))
    if doc_refs:
        docs = [read_doc(ref) for ref in doc_refs]
        texts = [i for i, (_, d) in enumerate(tasks) if not d]
        if not texts:
            tasks.append((docs[0]["title"], docs))
        for i in texts:
            tasks[i] = (tasks[i][0], docs)
    return tasks


def run_goals(args, cfg, team):
    from . import taskdocs
    from .flow import AgentSlots, Run
    try:
        tasks = tasks_from_args(args.goal, args.doc)
    except taskdocs.TaskDocError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    goals = [g for g, _ in tasks]
    from .flow import FlowError, apply_models, task_options
    try:
        options = task_options({"mode": args.mode, "skip": [x.strip() for x in args.skip.split(",") if x.strip()],
                                "models": dict(m.split("=", 1) for m in args.model if "=" in m)},
                               {a["id"] for a in cfg["agents"]})
    except FlowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if cfg["project"].get("use_projects", True):
        from . import projects
        try:
            projects.get(cfg, args.project)
        except projects.ProjectError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    many = len(goals) > 1
    out_lock = threading.Lock()

    def show(n):
        tag = f"[{n}] " if many else ""

        def on_event(kind, data):
            with out_lock:
                if kind == "message":
                    body = " ".join(str(data["content"]).split())
                    print(f"{tag}  {data['from']:>9} -> {data['to']:<9} {data['kind']:<16} {body[:90]}", file=sys.stderr)
                elif kind == "stage" and "result" not in data:
                    print(f"{tag}== {data['stage'].upper()}", file=sys.stderr)
        return on_event

    def approver(request):
        if args.approve:
            return True, "auto-approved (--approve)"
        if not sys.stdin.isatty():
            return False, "no approval given (non-interactive; use --approve or the dashboard)"
        with out_lock:  # one question at a time when several goals run
            answer = input(f"\nCEO approval needed: {request['question']} [y/N] ").strip().lower()
        return answer in ("y", "yes"), "" if answer in ("y", "yes") else "rejected in the terminal"

    slots = AgentSlots(cfg)
    limit = threading.BoundedSemaphore(max(1, int(cfg["project"].get("max_parallel_tasks", 3))))
    states = [None] * len(goals)

    def one(i, goal, docs):
        with limit:  # a Team per task: each task's agents work in that task's own workspace
            states[i] = Run(Team(apply_models(cfg, options["models"]), log=lambda m: None, brain=team.brain), goal,
                            approver=approver, on_event=show(i + 1), slots=slots, docs=docs, project_id=args.project,
                            options=options).execute()

    for goal, docs in tasks:
        for d in docs:
            print(f"task document: {d['name']} ({d['chars']} characters) -> {goal}", file=sys.stderr)
    threads = [threading.Thread(target=one, args=(i, g, d), daemon=True) for i, (g, d) in enumerate(tasks)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i, state in enumerate(states):
        if many:
            print(f"\n##### [{i + 1}] {goals[i]}")
        if state["status"] != "done":
            print(f"\nrun {state['status']}: {state['error']}", file=sys.stderr)
        rep = state.get("report") or {}
        if rep:
            print("\n=== CEO REPORT ===")
            for k in ("status", "progress", "qa_verdict", "fix_rounds", "deployed", "approval_needed", "blockers",
                      "recent_result", "next_action"):
                if k in rep:
                    print(f"{k.replace('_', ' ').upper():<16} {rep[k]}")
            for b in rep.get("blocker_list") or []:
                print(f"  blocker: {b}")
            if rep.get("summary"):
                print(f"\n{rep['summary']}")
        print(f"\nFull output saved in {state['dir']}")
        ws = state.get("workspace") or {}
        if ws.get("dir"):
            res = ws.get("result") or {}
            print(f"Work: project {ws['name']}, branch {ws['branch']}"
                  + (f", commit {res['commit']} ({res['files']} file(s))" if res.get("commit") else "")
                  + (", merged" if res.get("merged") else "") + (f" - {res['note']}" if res.get("note") else ""))
    if args.update_dashboard:
        for state in states:
            cfg = apply_run_to_config(cfg, state)
        save_config(cfg)
        sys.path.insert(0, ROOT)
        import generate_workspace
        generate_workspace.main()
    return 0 if all(s["status"] == "done" for s in states) else 1


if __name__ == "__main__":
    sys.exit(main())
