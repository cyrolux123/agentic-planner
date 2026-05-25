#!/usr/bin/env python3
"""
Resource-Constrained Agentic Planning Loop
==========================================
Entry point. Runs a single task passed on the command line, or starts
an interactive REPL with --interactive.

Model priority: llama3 (primary) → mistral (fallback).
The fallback activates automatically if llama3 is not found in Ollama.

Usage
-----
  python main.py "What is the capital of France?"
  python main.py --interactive
  python main.py --model mistral "Explain black holes"
"""

from __future__ import annotations

import argparse
import json
import sys

import ollama

from agent.agent import Agent, DEFAULT_MODEL, OLLAMA_HOST

FALLBACK_MODEL = "mistral"


def _resolve_model(requested: str) -> str:
    """
    Return `requested` if it is available in Ollama, else fall back to
    FALLBACK_MODEL.  Prints a clear warning when the fallback is used.
    """
    try:
        client = ollama.Client(host=OLLAMA_HOST)
        available = {m["name"].split(":")[0] for m in client.list()["models"]}
        if requested in available:
            return requested
        if FALLBACK_MODEL in available:
            print(
                f"[WARN] Model '{requested}' not found in Ollama. "
                f"Falling back to '{FALLBACK_MODEL}'.\n"
                f"       Pull it with: ollama pull {requested}"
            )
            return FALLBACK_MODEL
        # Neither model available — let Ollama error surface naturally
        print(
            f"[WARN] Neither '{requested}' nor '{FALLBACK_MODEL}' found in Ollama.\n"
            f"       Run: ollama pull {requested}"
        )
        return requested
    except Exception:
        # Ollama not reachable — return as-is and let the agent surface the error
        return requested


def _print_result(result) -> None:
    sep = "=" * 64
    print(f"\n{sep}")
    print("FINAL ANSWER")
    print(sep)
    print(result.answer)
    print(sep)
    print(
        json.dumps(
            {
                "stopped_reason": result.stopped_reason,
                "calls_used": result.calls_used,
                "total_cost_usd": round(result.total_cost, 6),
                "replans_triggered": result.replans_triggered,
            },
            indent=2,
        )
    )


def _run_single(task: str, model: str) -> None:
    model = _resolve_model(model)
    agent = Agent(model=model)
    result = agent.run(task)
    _print_result(result)


def _interactive(model: str) -> None:
    model = _resolve_model(model)
    print(
        f"Resource-Constrained Agent — Interactive Mode\n"
        f"Model: {model}   Budget: 10 calls / $0.20 per task\n"
        "Type 'quit' or 'exit' to stop.\n"
    )
    while True:
        try:
            task = input("Task> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not task:
            continue
        if task.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break
        # Fresh agent per task — budget resets cleanly
        agent = Agent(model=model)
        result = agent.run(task)
        _print_result(result)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resource-Constrained Agentic Planning Loop (Ollama / llama3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python main.py "What is the Pythagorean theorem?"\n'
            "  python main.py --interactive\n"
            '  python main.py --model mistral "Write Python code to reverse a string"\n'
        ),
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="Task for the agent to solve",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start interactive REPL (fresh agent + budget per task)",
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL}, fallback: {FALLBACK_MODEL})",
    )
    args = parser.parse_args()

    if args.interactive:
        _interactive(args.model)
    elif args.task:
        _run_single(args.task, args.model)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()