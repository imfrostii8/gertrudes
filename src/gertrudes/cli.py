"""Minimal CLI entry point for gertrudes."""

import argparse
import sys

from gertrudes.config import load_config
from gertrudes.implementer import run


def main():
    parser = argparse.ArgumentParser(
        prog="gertrudes",
        description="Implement GitHub issues using LLMs.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config YAML file (default: ./gertrudes.yaml)",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, EnvironmentError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        run(config)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
