# Web scraping and crawling

Raw HTML is mostly noise (nav, scripts, styling, ads). Never hold raw markup in
context. Extract the small clean slice you need with `scripts/web_extract.py`.

## 1. Inventory cheaply

For a crawl, map the site before fetching bodies:

```bash
python scripts/web_extract.py links https://example.com/blog --same-domain
```

Decide which URLs actually matter, then fetch only those.

## 2. Main content, not the whole page

```bash
python scripts/web_extract.py text https://example.com/article --main -o article.md
```

`--main` isolates the article block (via trafilatura when available) and
strips chrome. Far fewer tokens than the full DOM, and more accurate because the
model isn't distracted by menus and footers.

## 3. Structured fields by selector

When you need specific values, target them with CSS selectors and get JSON back:

```bash
python scripts/web_extract.py fields https://example.com/product \
    --select "title=h1" --select "price=.price" --select "sku=[data-sku]"
```

A selector that matches nothing returns `null` **and prints a WARNING** - so a
missing field is visible, never quietly invented.

## Crawling many pages

Process one page at a time: fetch -> extract the slice -> append a short record
to a file on disk -> move on. Never accumulate raw markup for many pages in
context. Aggregate the per-page records at the end.

## Be a good citizen

- Respect `robots.txt` and the site's terms; rate-limit your requests.
- Send a clear User-Agent (the script sets one).
- Don't scrape content you're not permitted to access; prefer official APIs/feeds.
- Never attempt to bypass CAPTCHAs, paywalls, or bot-detection.

## Verify before answering

- Each fact cites its source URL.
- Field values came from a selector that actually matched (no WARNING), not a guess.
- For a crawl, the per-page records were aggregated - you didn't summarize from memory.
- If the page rendered content via JS and the fetch got an empty body, say so
  (a static fetch can miss client-rendered data) rather than inventing values.
