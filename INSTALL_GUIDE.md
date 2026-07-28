# Token Saver — Setup Guide for Everyone

This guide installs Token Saver into Claude Desktop so you can ask questions
about big PDFs — and it only sends a tiny slice of the document to the AI
instead of the whole thing. **No coding, no Terminal, no Python.** One file, one
click.

On a large document that's typically **92–99% fewer tokens** — and a matching cut
in cost.

**Time needed:** about 5 minutes, plus a one-time download the first time you
use it.

---

## What Token Saver does (in one paragraph)

Normally, when you drop a 200-page PDF into an AI chat, the whole document gets
sent to the AI — which is slow, expensive, and actually makes the answers
worse. Token Saver keeps the document on your computer, quietly finds just the
handful of paragraphs that answer your question, and sends only those — with
the page number. You get faster, cheaper, page-cited answers, the document never
leaves your machine, and you save tokens and cost.

---

## Before you start — what you need

1. **Claude Desktop**, installed and up to date. (The Claude app, not the
   website. If you don't have it, download it from claude.ai and sign in.)
2. **The Token Saver extension file**: `token-saver-ccr.mcpb`.
   Download it from the project's **Releases** page.
3. **Some PDFs** with real text in them (not scans/photos of pages).

That's it. You do **not** need Python, Terminal, or any developer tools —
the extension brings everything it needs.

> **New to this?** There are only four steps, and you do them once:
> **install → turn on → pick a folder → ask your first question.**

---

## Step 1 — Install the extension

1. Open **Claude Desktop**.
2. Go to **Settings → Extensions**. (In some versions this is
   **Settings → Advanced Settings → Install Extensions** — either way, you're
   looking for the Extensions screen.)
3. Click **Install extension** (you may need to open **Advanced** or
   **Install from file**), and choose the `token-saver-ccr.mcpb` file you
   downloaded.
4. You'll see **Token Saver** appear in your extensions list.

You'll then land on the Token Saver page, which looks like this:

![The Token Saver extension page: a red security warning, the Enabled toggle, and the Configure button](docs/images/01-install-warning-and-enable.png)

### About that red warning — this is expected

Claude shows a red box saying the extension "will grant this extension access to
everything on your computer" and that the developer "has not been verified by
Anthropic."

**This is the standard message Claude shows for any extension installed from a
file rather than from Anthropic's official directory.** It appears for every
extension distributed this way — it is not a specific finding about Token Saver.

Two things worth knowing before you click past it:

- **Token Saver restricts itself to the one folder you choose in Step 3.** It
  refuses to read anything outside it. You are not, in practice, handing it your
  whole computer.
- **Nothing you open is uploaded anywhere by Token Saver.** See
  [A note on privacy](#a-note-on-privacy) at the end.

Only install extensions from a source you trust — the same rule as any app.

---

## Step 2 — Turn it on

On that same page, make sure the **Enabled** toggle is switched **on** (blue).

This is the single most common reason people think it "isn't working" — the
extension is installed but never switched on.

---

## Step 3 — Choose your documents folder (required)

Click **Configure** on the Token Saver page. You'll be asked to pick a folder.
**This step is required — Token Saver does nothing until you do it.**

![The Configure dialog with the documents folder set to Documents/Token Saver](docs/images/02-choose-folder.png)

**Best practice: make a new, small folder just for this** — for example a folder
called **Token Saver** inside your Documents — and put only the PDFs you want to
ask about in it. Don't point it at a huge, busy folder like all of Documents or
Downloads: a smaller folder is faster to search, and it lets Claude see your
files more clearly (a folder crammed with hundreds of files is noisier and can
get truncated). You can select more than one folder if you need to.

**Put your PDFs in that folder now, before you start asking questions.** Then
click **Save**.

This single choice is what makes everything else work:

- **It's how you can just ask.** Claude looks in this folder, so you can say
  *"my lease agreement"* instead of typing `/Users/you/Documents/lease.pdf`.
  No file paths, ever.
- **It's the safety boundary.** Token Saver can only read PDFs inside these
  folders, and refuses anything outside them.
- **It's how Claude knows what you have.** At startup the extension tells Claude
  the names of the documents in your folder — so when you say "summarize Blue
  Ocean", Claude knows you mean *your* copy, not the version it read on the
  internet.

> **Changed your folder or added new PDFs?** Fully quit and reopen Claude
> Desktop so it picks up the new list. (Closing the window isn't enough — see
> the troubleshooting table.)

---

## Step 4 — Your first question

Open a **new chat** and start with the simplest possible test:

> List my documents.

This just shows the PDFs Token Saver can see — a quick way to confirm your
folder is set up right before you ask anything real.

### You'll be asked for permission — click "Always allow"

The first time Claude uses Token Saver, it asks your permission:

![Claude asking permission: "Claude wants to use Ask from Token Saver", with Always allow and Deny buttons](docs/images/03-allow-tool-prompt.png)

Click **Always allow**. If you pick "Deny", Claude won't be able to read your
documents; if you allow it just once, you'll be asked again on every single
question. **Always allow** is the setting you want.

### The first question is slow — that's the one-time setup

The **first** time you actually use Token Saver, it quietly sets itself up: it
downloads its search engine and a small AI model (several hundred megabytes).
On a typical connection this takes **about 2–5 minutes**, and **it only happens
once**. After that, questions answer in a few seconds.

If your very first question seems to hang, that's what's happening. Give it a
few minutes — don't cancel it.

---

## How to use it — just ask

Once your folder is set, **there is nothing else to learn.** Ask about your
document by name, the way you'd mention it to a colleague. No file paths. No
commands. No "ingest".

**Copy this pattern:**
> What does **my lease agreement** say about the termination clause? **Cite the pages.**

Claude finds the closest matching file, reads it, and answers with page numbers —
in one go. The reply tells you which file it used:

> *(Reading lease-agreement.pdf — the closest match to your request.)*
> The agreement requires 60 days' written notice to terminate [p 3]…

If it ever picks the wrong file, just say *"no, I meant the other one"* and it
switches. (If several files match closely, it will instead show a short numbered
list and ask which — pick one and it continues.)

### Every answer shows what you saved

At the end of each answer you get a running total:

![The Token Saver session block showing 99% of tokens saved](docs/images/04-savings-block.png)

You can also ask *"run the savings tool"* at any time.

### The five things you'll actually do

| You want to… | Just say |
|---|---|
| Ask about a document | *"What does **my Q3 report** say about revenue? Cite the pages."* |
| Ask a follow-up | *"What does it say about risks?"* (no reload needed) |
| See what's available | *"List my documents."* |
| Use the newest file | *"Summarize my most recent PDF."* |
| Switch documents | *"Clear everything,"* then ask about the next one |

### Two habits that make it work every time

1. **Say "my"** — *my* report, *my* lease, *my* PDF. It tells Claude you mean
   your file, not something it already knows.
2. **Ask it to cite the pages.** A real page number can only come from your
   document, so it's both the best way to trigger the tool and your proof it
   actually read your file.

---

## Check it's working (6 quick tests)

If you want to confirm everything is set up correctly — or you're testing this
for someone else — run these in a **new chat**. Each one takes a few seconds.

**1. Ask by name (the main event).**
> What does **my** [part of a filename, e.g. "Q3 report"] say about [a topic
> that's really in it]? **Cite the pages.**

✅ It names the file it read ("Reading Q3-report.pdf…") and answers **with page
numbers**, in one step — no paths, no "ingest", no "which file?" prompt.

**2. Ask a follow-up.**
> What else does it say about [a related topic]?

✅ It answers **without reloading** the document.

**3. Check the savings.** Look at the end of any answer.

✅ Every answer ends with a "Token Saver · session so far" block showing tokens
saved and an estimated dollar figure.

**4. Ask something that isn't in the document.** This is the important one.
> What does my [document] say about penguins?

✅ It says it **can't find anything relevant** — it does **not** invent an answer.
This is what makes the page citations trustworthy.

**5. Ask by topic, without naming a file.**

Pick a subject one of your PDFs covers and ask as if it were general knowledge —
don't say "my", don't use the filename:
> What did the Supreme Court decide about affirmative action in college admissions?

(Substitute a topic from your own folder: a drug's side effects, a company's
annual results, a regulation's penalties.)

✅ The answer **cites pages from your PDF**.
❌ A generic summary with no page numbers means it answered from memory — say
*"read my local copy and cite the pages"* and it should recover.

**6. Clear everything.**
> Clear everything.

✅ It confirms the document was dropped from memory **and** says the savings
counter was reset. Ask something new afterwards: the savings block restarts from
zero rather than carrying the old totals.

**If all six pass, it's working.**

### Which Claude model should I use?

**Any current Claude model works. Sonnet or Opus is recommended; Haiku works but
needs a little more steering.** All three were tested end to end against the same
16-PDF folder.

| Model | What to expect |
|---|---|
| **Opus** | Best. Picks the right file from a vague or topic-only request, and says when it is unsure. |
| **Sonnet** | Recommended default. Matches Opus on nearly everything; occasionally needs the word "my". |
| **Haiku** | Works, and every answer still carries page citations. Expect roughly one extra correction turn on an ambiguous request — say "list my documents", then ask again. |

The two habits above (say **"my"**, ask it to **cite the pages**) matter more on
smaller models than larger ones. If a model answers *without* a page citation, it
answered from memory rather than reading your file — add "using my file, cite the
pages" and it will.

Earlier versions were genuinely unreliable on smaller models: naming a document
produced a "use this file?" prompt the model had to relay and then act on in a
second step, and lighter models routinely dropped that step, so nothing happened.
That handshake is gone — Token Saver now finds the file and answers in **one
step**, naming the file it used.

---

## Getting Claude to actually read YOUR file (important)

Claude knows a lot already. If you name a **famous book or a well-known report**,
it may answer from memory or the web instead of opening your file — you'll get a
generic summary with **no page citations**. Token Saver only helps when Claude
actually calls it. Two rules make that reliable:

**1. Make it clear you mean YOUR file.** Point at your documents in the wording:

| Weak (may answer from memory) | Strong (reads your file) |
|---|---|
| "Summarize Blue Ocean Strategy" | "Summarize **my** Blue Ocean Strategy **PDF** and cite pages" |
| "What is the theory of X?" | "What does **my document** say about X? Cite the page." |
| "Tell me about the annual report" | "Using **my files**, summarize the annual report with page numbers" |

Trigger words that reliably route to your folder: **my / my file / my documents /
the PDF / in my folder / cite the page(s)**.

**2. If it answers from memory anyway, correct it in one line:**
> No — read my local copy with Token Saver and cite the pages.

Then it will look in your folder. Asking it to **cite pages** is the best habit:
a real citation only comes from your file, so it's both the point *and* the proof
it used your document.

If it says the file isn't found, run **"List my documents"** to see the exact
names Token Saver can see, then use one of those.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| Tools don't appear in Claude | Make sure the extension is **enabled** (Step 2), then **fully quit** Claude Desktop (Mac: Cmd+Q; Windows: tray icon → Quit) and reopen it. Closing the window isn't enough. |
| First question hangs for a while | That's the one-time setup download (Step 4). Give it 2–5 minutes; later questions are fast. |
| You clicked "Deny" on the permission prompt | Start a new chat and ask again — the prompt reappears. Choose **Always allow** this time. |
| Claude replies, but never uses Token Saver | Nothing is broken — it's answering from memory instead of opening your file. Check the extension is toggled on for that chat, then see "Getting Claude to actually read YOUR file" below. |
| Answers have no page numbers | Claude probably answered from memory — see "Getting Claude to actually read YOUR file" above. |
| "outside the allowed folders" | The PDF isn't in a folder you picked in Step 3. Add its folder in **Settings → Extensions → Token Saver → Configure**, or move the PDF there. |
| "no such file" / can't find it | Ask **"List my documents"** to see the exact names it can see, then use one of those. |
| "no extractable text (scanned PDF?)" | The PDF is images, not text. Run it through OCR (e.g. the free `ocrmypdf`) first. |
| Added a new PDF and it can't see it | Fully quit and reopen Claude Desktop — the document list is read at startup. |
| Still stuck | Check the log. Mac: **~/Library/Logs/Claude/**; Windows: **%APPDATA%\Claude\logs\**. Open the file named after `token-saver-ccr` — it shows the real error. |

### If the AI model can't load

If the extension can't download or load its AI model (no internet, a slow
connection, a locked-down machine), it **does not break** — it automatically
falls back to matching your words instead of their meaning, and every answer
tells you so ("keyword-only mode"). You still get page-cited answers from your
own documents; only synonym matching is off, so phrase questions using words
that actually appear in the document.

It recovers on its own once the model can load — just restart Claude Desktop.

---

## A note on privacy

Your documents stay on your computer. Token Saver reads them locally, does the
searching locally with a small model that needs no internet after the first
download, and only ever sends the AI the few short paragraphs that answer your
question — never the whole file. Nothing is uploaded anywhere by Token Saver
itself.

For sensitive work (legal, medical, financial), use Step 3 to lock it to
specific folders — it will refuse to read anything outside them.

---

## Quick reference card

    Setup (once):
      1. Have Claude Desktop
      2. Download token-saver-ccr.mcpb from the Releases page
      3. Claude Desktop -> Settings -> Extensions -> Install extension
           -> pick the .mcpb file   (red warning is normal - see Step 1)
      4. Switch the Enabled toggle ON
      5. REQUIRED: Configure -> choose a small folder holding your PDFs
      6. First question: "List my documents."
           -> click ALWAYS ALLOW on the permission prompt
           -> first run downloads the engine (one-time, 2-5 min)

    Use (anytime) - no paths, no commands:
      "What does MY <document> say about <topic>? Cite the pages."
           -> Claude names the file it read, and cites pages
      "List my documents."
      Follow-ups just work: "What does it say about X?"
      "Clear everything."      (switch to another document)
      (savings appear automatically at the end of every answer)

    Two habits:
      - say "my" (my report, my lease)   -> means YOUR file, not Claude's memory
      - ask it to "cite the pages"       -> the proof it really read your file

    Check it's working (in a new chat):
      1. "What does MY <doc> say about <topic>? Cite pages."  -> names file, cites
      2. Follow-up question                                   -> no reload
      3. Look at the end of any answer                        -> savings block
      4. Ask about something NOT in the PDF                   -> says it can't find it
      5. Ask by topic without naming the file                 -> still cites your pages
      6. "Clear everything."                                  -> frees RAM + resets savings

    If the AI model can't load, it degrades automatically to word-matching
    and says so in the answer - nothing to configure.
