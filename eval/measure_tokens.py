#!/usr/bin/env python3
"""measure_tokens.py - prove the skill saves tokens AND keeps accuracy.

Runs the same questions two ways over the same PDF:
  A) NAIVE  - the whole document is stuffed into context.
  B) SKILL  - only an anchored retrieval slice (scripts/retrieve.py) is sent.

Reports input/output tokens for each and prints both answers side by side, so
you measure accuracy alongside the token delta -- not just cost.

Modes:
  (default)     call the Anthropic API; report real token usage + answers
  --count-only  count input tokens via the API token counter; no model run
  --dry-run     no API at all; rough char/4 token estimate for a quick preview

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  printf "What is the revenue recognition policy?\nWhat were GDPR obligations?\n" > q.txt
  python eval/measure_tokens.py --pdf report.pdf --questions q.txt

Dependencies: pypdf; anthropic (unless --dry-run).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

MODEL = "claude-3-5-sonnet-latest"
HERE = Path(__file__).resolve().parent
RETRIEVE = HERE.parent / "scripts" / "retrieve.py"


def eprint(*a):
    print(*a, file=sys.stderr)


def full_text(pdf: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def slice_for(pdf: Path, question: str) -> str:
    """Call retrieve.py and capture the anchored slice from stdout."""
    proc = subprocess.run(
        [sys.executable, str(RETRIEVE), str(pdf), "--query", question,
         "--top-k", "5", "--neighbors", "1", "--anchors", "--follow-xrefs"],
        capture_output=True, text=True,
    )
    return proc.stdout


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def ask(client, context: str, question: str):
    msg = client.messages.create(
        model=MODEL, max_tokens=400,
        messages=[{"role": "user",
                   "content": f"Use ONLY the material below. Cite pages. "
                              f"If the answer is not present, say so.\n\n"
                              f"=== MATERIAL ===\n{context}\n\n=== QUESTION ===\n{question}"}],
    )
    return msg.content[0].text.strip(), msg.usage.input_tokens, msg.usage.output_tokens


def count_input(client, context: str, question: str) -> int:
    r = client.messages.count_tokens(
        model=MODEL,
        messages=[{"role": "user", "content": f"{context}\n\n{question}"}],
    )
    return r.input_tokens


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    questions = [q.strip() for q in args.questions.read_text(encoding="utf-8").splitlines() if q.strip()]
    whole = full_text(args.pdf)

    client = None
    if not args.dry_run:
        try:
            import anthropic
        except ImportError:
            eprint("Install anthropic, or use --dry-run:  pip install anthropic")
            sys.exit(2)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            eprint("Set ANTHROPIC_API_KEY, or use --dry-run.")
            sys.exit(2)
        client = anthropic.Anthropic()

    naive_in = skill_in = naive_out = skill_out = 0
    print(f"# Token Saver A/B  ({args.pdf.name}, {len(questions)} question(s))\n")

    for q in questions:
        sl = slice_for(args.pdf, q)
        print("=" * 72)
        print(f"Q: {q}")

        if args.dry_run:
            ni, si = est_tokens(whole), est_tokens(sl)
            naive_in += ni; skill_in += si
            print(f"  [dry-run] naive input ~{ni} tok   skill input ~{si} tok   "
                  f"(slice = {si * 100 // max(ni,1)}% of naive)")
        elif args.count_only:
            ni = count_input(client, whole, q)
            si = count_input(client, sl, q)
            naive_in += ni; skill_in += si
            print(f"  naive input {ni} tok   skill input {si} tok   "
                  f"(slice = {si * 100 // max(ni,1)}% of naive)")
        else:
            na, ni, no = ask(client, whole, q)
            sa, si, so = ask(client, sl, q)
            naive_in += ni; skill_in += si; naive_out += no; skill_out += so
            print(f"  tokens  naive in/out {ni}/{no}   skill in/out {si}/{so}")
            print(f"  NAIVE answer: {na}")
            print(f"  SKILL answer: {sa}")

    print("=" * 72)
    print(f"TOTAL input tokens   naive {naive_in}   skill {skill_in}   "
          f"saved {naive_in - skill_in} ({(naive_in - skill_in) * 100 // max(naive_in,1)}%)")
    if naive_out or skill_out:
        print(f"TOTAL output tokens  naive {naive_out}   skill {skill_out}")
    print("Note: across N follow-ups the naive cost re-pays the whole doc each turn; "
          "the slice does not. Savings compound.")


if __name__ == "__main__":
    main()
