# Token Saver

A portable AI **skill** for deep work over heavy inputs — PDF analysis, large dataset/log analysis, and web scraping — **without losing accuracy**.

Ships as a native [Agent Skill](https://docs.claude.com) for Claude, plus paste-in instruction files for ChatGPT and Gemini.

## The idea

**Keep bulk data out of the context window. Do bulk work in code. Bring only a _precise, verified slice_ into the model's reasoning.**

This wins on two fronts at once:

- **Cost** — context is re-sent on every turn, so a 200-page PDF dumped in is re-paid on every follow-up. A small slice is paid once.
- **Accuracy** — a model buried in irrelevant text reasons *worse* (relevant facts get lost in the middle). A tight, on-point context is more reliable.

So the failure mode is never "too little context" — it's **"the wrong little."** Token Saver's whole job is to retrieve precisely and verify the answer against what was retrieved.

## How accuracy is protected

- **Accuracy contract** — ground and cite every claim; abstain or widen instead of guessing from prior knowledge; verify before finalizing.
- **Retrieval that doesn't miss** — always include structural anchors (outline, defined terms, footnotes), hybrid keyword + semantic matching, and neighbor expansion.
- **Escalation ladder** — start with the cheapest slice; widen only when a verification check fails. Cheap on easy docs, thorough on hard ones, never blindly maximal.

## What's inside

```
token-saver/
├── SKILL.md              # Claude Agent Skill: principle, accuracy contract, workflow, ladder
├── README.md · LICENSE · requirements.txt · .gitignore
├── references/           # Claude loads these on demand (progressive disclosure)
│   ├── pdf.md            # PDF / long-document tactics
│   ├── data-analysis.md  # CSV / logs / JSON / codebase tactics
│   ├── scraping.md       # web scraping / crawling tactics
│   ├── accuracy.md       # grounding, precise retrieval, verification
│   └── savings.md        # caching, stripping, budgets, offloading
├── scripts/              # run locally; output stays tiny, bulk never enters context
│   ├── retrieve.py       # precise citable slice: anchors + hybrid match + neighbors + coverage
│   ├── pdf_inspect.py    # inventory, outline, scanned-page flag, text/search/tables, chunking
│   └── web_extract.py    # main-content/clean text, selector field extraction, links
├── eval/
│   └── measure_tokens.py # A/B harness: exact token usage AND answer comparison
└── prompts/
    ├── chatgpt-instructions.md # paste into a Custom GPT
    └── gemini-gem.md           # paste into a Gem
```

## Install / use

- **Claude (primary):** add this folder as a skill (Claude.ai, Claude Code, Cowork, or the API per the Agent Skills docs). Claude reads `SKILL.md` and loads `references/*.md` on demand.
- **ChatGPT:** paste `prompts/chatgpt-instructions.md` into a Custom GPT → Instructions (or a system message). Best with the code-interpreter / data-analysis tool enabled.
- **Gemini:** paste `prompts/gemini-gem.md` into a Gem instruction box.

> Install UIs change; check each platform's current docs for the exact menu path. The instructions themselves are platform-independent.

## Quickstart (scripts)

```bash
pip install -r requirements.txt   # or install only what you use

# Precise, citable slice for a question (the accuracy workhorse)
python scripts/retrieve.py report.pdf --query "revenue recognition for SaaS" \
  --top-k 5 --neighbors 1 --anchors --follow-xrefs -o slice.txt

# PDF inventory (flags scanned pages), search, tables, chunking
python scripts/pdf_inspect.py info report.pdf
python scripts/pdf_inspect.py search report.pdf "clause 7.2" --neighbors 1
python scripts/pdf_inspect.py tables report.pdf --pages 12-14 -o tables/
python scripts/pdf_inspect.py map report.pdf --chunk 4 -o chunks/

# Web: main content, structured fields, links
python scripts/web_extract.py text https://example.com/article --main -o article.md
python scripts/web_extract.py fields https://example.com/p --select "title=h1" --select "price=.price"
python scripts/web_extract.py links https://example.com/blog --same-domain
```

`retrieve.py` uses semantic matching automatically if `sentence-transformers` is installed; otherwise it falls back to keyword + structural anchors.

## Prove it works (tokens AND accuracy)

`eval/measure_tokens.py` runs the same task two ways — naive full-document-in-context vs. the skill's anchored retrieval — over the same questions, and reports token usage *and* the answers side by side.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
printf "What is the revenue recognition policy?\nWhat were GDPR obligations?\n" > q.txt

python eval/measure_tokens.py --pdf report.pdf --questions q.txt              # tokens (in+out) + answers
python eval/measure_tokens.py --pdf report.pdf --questions q.txt --count-only # input context size, no model run
python eval/measure_tokens.py --pdf report.pdf --questions q.txt --dry-run    # no API; rough char/4 preview
```

The savings compound across turns: the naive approach re-pays for the whole document on every follow-up. See `references/savings.md`.

## Why it works

| Approach | What touches context | On a 200-page PDF, 5 questions |
| --- | --- | --- |
| Naive: load the whole document | ~150k tokens of raw text | re-paid every turn (~750k total) |
| Token Saver: inventory → retrieve → verify | anchors + a few pages + citations | a small fraction, accuracy verified |

The same pattern applies to a million-row CSV (a checkable aggregate, not the rows) and a 100-page codebase (the relevant files, not the tree).

## License

MIT — use, modify, and share freely.
