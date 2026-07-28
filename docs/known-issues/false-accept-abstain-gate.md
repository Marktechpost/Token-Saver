# Known issue: the abstain gate can false-accept on an incidental keyword

**Status:** open · **Severity:** correctness (returns an irrelevant passage
instead of abstaining) · **Affects:** all versions including 0.3.0

## Summary

The eligibility gate in `Store.search` admits a chunk if it clears the semantic
floor **or** has any keyword hit:

```python
eligible = (sem >= index_store.SEM_FLOOR) | (kw > 0)
```

`kw > 0` is a *presence* test, not a relevance threshold. A single incidental
term shared between an off-topic question and an otherwise unrelated passage is
enough to make that passage eligible. Once eligible, min-max normalisation can
scale it to a high combined score simply because nothing better is competing,
and it is returned as if it answered the question.

The system is designed to **abstain rather than guess**. This is the one path
where it guesses.

## Why it is not caught by the current tests

The abstain tests use questions with *no* lexical overlap at all ("quantum
entanglement in birdsong", "penguins"), which the gate correctly rejects. The
failure needs a query that is off-topic **but shares a common word** with the
document — the adversarial middle ground the suite does not currently cover.

## Reproduction sketch

1. Load any document containing a common word such as "notes", "report",
   "section", or "agreement".
2. Ask a question that is clearly off-topic for that document but contains one
   of those words.
3. Observe a returned `<document-chunk>` rather than the abstain message
   *"No relevant chunks for …"*.

The same class of defect was already fixed **once**, in a neighbouring
component: the document resolver's content probe used to accept a file on a
single incidental term ("quantum chromodynamics lecture **notes**" matched
`attention-paper-notes.pdf`). That was fixed by requiring ≥2 distinct query
terms (`MIN_PROBE_TERMS`). The retrieval gate has not had the equivalent fix.

## Impact

- **Not silent.** Every answer carries page citations, so a user who checks the
  cited page sees the passage does not support the claim.
- **Bounded.** It surfaces a wrong passage; it does not leak files outside the
  approved folders and does not affect the security envelope.
- The practical risk is a model confabulating around a weakly-related passage
  instead of saying "not in this document".

## Candidate fixes (not yet implemented)

1. **Require more than presence.** Gate on `kw` clearing a small absolute or
   relative threshold rather than `> 0` — mirroring `MIN_PROBE_TERMS` in the
   resolver.
2. **Require ≥2 distinct matched query terms** for a keyword-only eligible chunk
   (single-term queries exempted, since for those the one term is the whole
   question).
3. **Add an absolute floor on the blended score**, so min-max cannot promote the
   best of a uniformly bad field.

Option 2 is the closest analogue to the fix that already worked in the resolver.

Any fix must be measured against `eval/retrieval_eval.py` for false-abstain
regression: the current false-abstain rate is **0.00** and tightening the gate
is exactly the change that could push it above zero. That trade-off is the whole
difficulty, and is why this is filed rather than patched hastily.

## References

- `scripts/mcp_server.py` — `Store.search`, the `eligible = …` line
- `scripts/index_store.py` — the same gate in the durable-index path (`query`)
- `scripts/mcp_server.py` — `_content_matches` / `MIN_PROBE_TERMS`, the analogous
  fix already shipped for document resolution
