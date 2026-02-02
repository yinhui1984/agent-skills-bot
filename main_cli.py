from agent_skills_bot.interfaces.cli import run_cli_loop


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="agent-skills-bot CLI")
    parser.add_argument("query", nargs="*", help="Query to execute")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single query and exit (disable prompt loop)",
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="Disable multi-step tool loop for a single query",
    )
    parser.add_argument(
        "--max-loop-count",
        type=int,
        default=10,
        help="Max tool iterations per query (default: 10)",
    )
    args = parser.parse_args()

    query = " ".join(args.query).strip() or None
    run_cli_loop(
        query,
        loop=not args.once,
        tool_loop=not args.no_loop,
        max_loop_count=args.max_loop_count,
    )
