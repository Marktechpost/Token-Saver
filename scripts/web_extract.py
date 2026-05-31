#!/usr/bin/env python3
"""web_extract.py - pull a small, clean slice from a web page (not raw HTML).

Subcommands (run with --help on each):
  text    clean text or markdown of the page; --main isolates the article block
  fields  structured extraction by CSS selector: --select "name=selector"
  links   list links; --same-domain to keep only on-site links

Raw HTML is heavy and noisy. Extract only what the task needs and write it to a
file; let the model reason over the small result, not the markup. Empty
selectors WARN instead of silently inviting a guessed value.

Dependencies: requests, beautifulsoup4 (+ lxml). trafilatura optional for --main.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

UA = "Mozilla/5.0 (compatible; TokenSaver/1.0; +https://github.com/Marktechpost/Token-Saver)"


def eprint(*a):
    print(*a, file=sys.stderr)


def fetch(url: str) -> str:
    try:
        import requests
    except ImportError:
        eprint("Install requests:  pip install requests")
        sys.exit(2)
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return resp.text


def soup_of(html: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        eprint("Install beautifulsoup4:  pip install beautifulsoup4 lxml")
        sys.exit(2)
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def write_or_print(text: str, out):
    if out:
        Path(out).write_text(text, encoding="utf-8")
        eprint(f"Wrote {len(text)} chars (~{len(text)//4} tokens) -> {out}")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def cmd_text(args):
    if args.main:
        try:
            import trafilatura
            downloaded = fetch(args.url)
            extracted = trafilatura.extract(
                downloaded, output_format="markdown" if args.markdown else "txt",
                include_links=False, include_comments=False,
            )
            if extracted:
                write_or_print(extracted, args.out)
                return
            eprint("trafilatura found no main content; falling back to full-text strip.")
        except ImportError:
            eprint("--main works best with trafilatura (pip install trafilatura); falling back.")
    soup = soup_of(fetch(args.url))
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    write_or_print("\n".join(lines), args.out)


def cmd_fields(args):
    soup = soup_of(fetch(args.url))
    results, empties = {}, []
    for spec in args.select:
        if "=" not in spec:
            eprint(f"Bad --select {spec!r}; expected name=selector"); continue
        name, selector = spec.split("=", 1)
        name, selector = name.strip(), selector.strip()
        el = soup.select_one(selector)
        if el is None:
            results[name] = None
            empties.append((name, selector))
        else:
            results[name] = el.get_text(" ", strip=True)
    import json
    write_or_print(json.dumps(results, indent=2, ensure_ascii=False), args.out)
    if empties:
        for name, selector in empties:
            eprint(f"WARNING: selector for {name!r} ({selector}) matched nothing -> value is null, not guessed.")


def cmd_links(args):
    soup = soup_of(fetch(args.url))
    base = urlparse(args.url).netloc
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(args.url, a["href"])
        if args.same_domain and urlparse(href).netloc != base:
            continue
        if href not in seen:
            seen.add(href)
            text = a.get_text(" ", strip=True)
            out.append(f"{href}\t{text}" if text else href)
    write_or_print("\n".join(out), args.out)
    eprint(f"{len(out)} link(s){' (same-domain)' if args.same_domain else ''}.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("text"); p.add_argument("url")
    p.add_argument("--main", action="store_true", help="isolate the main article block")
    p.add_argument("--markdown", action="store_true", help="markdown output (with --main)")
    p.add_argument("-o", "--out"); p.set_defaults(func=cmd_text)

    p = sub.add_parser("fields"); p.add_argument("url")
    p.add_argument("--select", action="append", default=[], metavar="name=selector")
    p.add_argument("-o", "--out"); p.set_defaults(func=cmd_fields)

    p = sub.add_parser("links"); p.add_argument("url")
    p.add_argument("--same-domain", action="store_true")
    p.add_argument("-o", "--out"); p.set_defaults(func=cmd_links)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
