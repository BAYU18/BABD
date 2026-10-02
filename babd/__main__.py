"""Command line for the AI development team.

  python -m babd check                         ping every agent's LLM
  python -m babd ask <agent> "message"         one message to one agent
  python -m babd chat <agent>                  interactive chat with one agent
  python -m babd run "goal" [--update-dashboard]
                                               full team run: plan -> work -> CEO report
"""
import argparse
import sys

from .config import ROOT, load_config, load_dotenv, save_config
from .llm import LLMError
from .team import Team, apply_report_to_dashboard


def main(argv=None):
    load_dotenv()
    p = argparse.ArgumentParser(prog="python -m babd", description="Run the AI development team.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="ping every agent's LLM")
    a = sub.add_parser("ask", help="send one message to one agent")
    a.add_argument("agent")
    a.add_argument("message")
    c = sub.add_parser("chat", help="interactive chat with one agent")
    c.add_argument("agent")
    r = sub.add_parser("run", help="full team run on a goal")
    r.add_argument("goal")
    r.add_argument("--update-dashboard", action="store_true",
                   help="write the CEO report into agents.json and regenerate workspace.svg")
    args = p.parse_args(argv)

    cfg = load_config()
    team = Team(cfg, log=lambda m: print(m, file=sys.stderr))

    if args.cmd == "check":
        ok_all = True
        for agent_id, (ok, msg) in team.check().items():
            ag = team.by_id[agent_id]
            llm = ag.cfg["llm"]
            print(f"{'OK  ' if ok else 'FAIL'} {ag.name:<12} {llm['model']} @ {llm.get('base_url', '')}  "
                  f"{msg.strip()[:120]}")
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
            print(f"Chatting with {agent.name} ({agent.cfg['llm']['model']}). Empty line or Ctrl-D to quit.")
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
        try:
            result = team.run(args.goal)
        except LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        rep = result["report"]
        print("\n=== CEO REPORT ===")
        for k in ("status", "progress", "current_goal", "active_task", "approval_needed", "blockers",
                  "recent_result", "next_action"):
            if k in rep:
                print(f"{k.replace('_', ' ').upper():<16} {rep[k]}")
        if rep.get("summary"):
            print(f"\n{rep['summary']}")
        print(f"\nFull output saved in {result['dir']}")
        if args.update_dashboard:
            save_config(apply_report_to_dashboard(cfg, rep))
            sys.path.insert(0, ROOT)
            import generate_workspace
            generate_workspace.main()
        return 0


if __name__ == "__main__":
    sys.exit(main())
