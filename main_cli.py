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
    args = parser.parse_args()

    query = " ".join(args.query).strip() or None
    run_cli_loop(query, loop=not args.once)
