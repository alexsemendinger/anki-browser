#!/usr/bin/env python3
"""Entry point. `python run.py` then open http://127.0.0.1:5151."""
import argparse

from backend.app import create_app
from backend.config import load_config


def main():
    parser = argparse.ArgumentParser(description="Anki Deck Workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5151)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    app = create_app(cfg)
    print("Anki Deck Workbench  ->  http://%s:%d" % (args.host, args.port))
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
