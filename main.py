"""Entry point.  `python main.py` = CLI,  `python main.py --web` = web UI."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="AI Memory Agent")
    parser.add_argument("--web", action="store_true", help="start the local web UI")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    from memory_agent.app import build_agent
    try:
        agent = build_agent()
    except ConnectionError:                      # Mem0 contacts Ollama while initialising
        raise SystemExit("Could not connect to Ollama. Start it with `ollama serve` "
                         "(and make sure the models are pulled: `ollama pull llama3.2:3b` and "
                         "`ollama pull nomic-embed-text`), then run this again.")
    except RuntimeError as exc:
        if "already accessed" in str(exc):      # Qdrant local mode allows one process per folder
            raise SystemExit("The memory store is already open in another AI Memory Agent process "
                             "(the CLI or web server). Stop that one first: local Qdrant allows one at a time.")
        raise
    if args.web:
        from memory_agent.web import run_web
        run_web(agent, args.port)
    else:
        from memory_agent.cli import run_cli
        run_cli(agent)


if __name__ == "__main__":
    main()
