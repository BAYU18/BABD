"""Command line for the AI development team.

  python -m babd check                         ping every agent through its harness and LLM
  python -m babd harnesses                     list the available harness types
  python -m babd use <agent> <harness> [--set key=value ...]
                                               select a harness: installs and configures it
  python -m babd setup [agent ...]             install + configure every agent's harness
  python -m babd dashboard [--port 8800]       web panel: configure, command and watch the agents
  python -m babd brain [words ...]             team memory (GBrain): status, or recall about some words
  python -m babd ask <agent> "message"         one message to one agent
  python -m babd chat <agent>                  interactive chat with one agent
  python -m babd run "goal" [--approve] [--update-dashboard]
                                               full team run: plan -> work -> CEO report
"""
import argparse
import json
import sys

from .config import ROOT, load_config, load_dotenv, save_config
from .gbrain import BrainError, GBrain, format_memory
from .harness import HARNESSES, create_harness, select_harness
from .llm import LLMError
from .team import Team, apply_run_to_config


def main(argv=None):
    load_dotenv()
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
    a = sub.add_parser("ask", help="send one message to one agent")
    a.add_argument("agent")
    a.add_argument("message")
    c = sub.add_parser("chat", help="interactive chat with one agent")
    c.add_argument("agent")
    r = sub.add_parser("run", help="full team run on a goal")
    r.add_argument("goal")
    r.add_argument("--approve", action="store_true", help="approve the deploy without asking (CEO approval gate)")
    r.add_argument("--update-dashboard", action="store_true",
                   help="write the CEO report into agents.json and regenerate workspace.svg")
    args = p.parse_args(argv)

    if args.cmd == "harnesses":
        for kind, cls in HARNESSES.items():
            print(f"{kind:<15} {cls.label:<16} {(cls.__doc__ or '').strip().splitlines()[0]}")
        return 0

    if args.cmd == "dashboard":
        from .dashboard.server import serve
        serve(args.host, args.port, open_browser=not args.no_browser)
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
        def show(kind, data):
            if kind == "message":
                body = " ".join(str(data["content"]).split())
                print(f"  {data['from']:>9} -> {data['to']:<9} {data['kind']:<16} {body[:90]}", file=sys.stderr)
            elif kind == "stage" and "result" not in data:
                print(f"== {data['stage'].upper()}", file=sys.stderr)

        def approver(request):
            if args.approve:
                return True, "auto-approved (--approve)"
            if not sys.stdin.isatty():
                return False, "no approval given (non-interactive; use --approve or the dashboard)"
            answer = input(f"\nCEO approval needed: {request['question']} [y/N] ").strip().lower()
            return answer in ("y", "yes"), "" if answer in ("y", "yes") else "rejected in the terminal"

        state = team.run(args.goal, approver=approver, on_event=show)
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
        if args.update_dashboard:
            save_config(apply_run_to_config(cfg, state))
            sys.path.insert(0, ROOT)
            import generate_workspace
            generate_workspace.main()
        return 0 if state["status"] == "done" else 1

if __name__ == "__main__":
    sys.exit(main())
