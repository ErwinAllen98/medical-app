# 🧠 Second Brain — Closed-Loop Adaptive Medical Learning

A personal medical **Second Brain** that connects **NotebookLM → Anki/FSRS → Claude → targeted
re-study → mastery → Notion** into one continuous feedback loop.

It is **not** a flashcard generator. It is optimised for a single question:

> **Which clinically important knowledge gaps do I have, why do they exist,
> and can the system systematically eliminate them?**

The system continuously answers four questions:
**What don't I know? · Why don't I know it? · Where in my sources can I fix it? · How do we know I've mastered it?**

*Dr Erfan Alinejad Ghadi — Iran Medical Council No. 219890*

---

## The loop

```
AUTHORITATIVE SOURCES
   ↓  guidelines · textbooks · reviews · lecture notes · PDFs · slides
GEMINI NOTEBOOKLM ......... source-grounded extraction (no outside facts)
   ↓
KNOWLEDGE UNITS + MCQs + CARDS ... every item traceable to chapter/section/page
   ↓  validation: untraceable items are rejected
ANKICONNECT ............... automatic transfer, no copy-paste
   ↓
ANKI + FSRS ............... scheduling, stability, difficulty, retrievability
   ↓  performance data pulled back
CLAUDE .................... WHY the knowledge keeps failing (10-type taxonomy)
   ↓
CUMULATIVE WEAKNESS PROFILE ... patterns across cards, not isolated lapses
   ↓
SOURCE LOCALISATION ....... the exact table/algorithm/paragraph to reread
   ↓
TARGETED RE-STUDY ......... WHAT → WHERE → WHY → HOW (+ what to ignore)
   ↓
ADAPTIVE RE-QUESTIONING ... new formulations at the weakest cognitive layer
   ↓
MASTERY CRITERION ......... repeated · time-spread · multi-format · applied
   ↓
NOTION .................... mastered knowledge + the weakness history behind it
   ↺  new performance data → Claude → continuous improvement
```

---

## What is actually implemented

| Layer | Module | What it does |
|---|---|---|
| 1–2 Extraction | `secondbrain/extraction.py` | Builds the source-grounded NotebookLM/Gemini prompt, parses the JSON, **rejects any knowledge unit that cannot name its chapter/section/page** |
| 3 Transfer | `secondbrain/ankiweb.py` | **Phone path**: drives a real Anki collection with the `anki` library and syncs it with AnkiWeb, so AnkiDroid only has to press Sync |
| 3 Transfer | `secondbrain/anki.py` | Desktop path: AnkiConnect client (deck + note type auto-created) and `.apkg` export via genanki |
| 4 Sensor | `secondbrain/colpkg.py` | Reads the review log straight out of an AnkiDroid export (`.colpkg`/`.apkg`, incl. zstd format) |
| 4 Sensor | `secondbrain/ingest.py` | Flexible CSV import of Anki revlog, local FSRS recomputation (`fsrs` package) |
| 5–6 Diagnosis | `secondbrain/diagnostics.py`, `secondbrain/claude.py` | Cumulative Weakness Profile, failure signatures, heuristic error hypotheses; longitudinal dossier + Claude prompt/parser |
| 6 Scoring | `secondbrain/diagnostics.py` | **Knowledge-Gap Score** = frequency × severity × recency × retrieval difficulty × low stability, ranked as Priority 1…N |
| 7–8 Repair | `secondbrain/prescription.py` | **Learning Prescription** (WHAT · WHY · WHERE · WHAT TO STUDY · HOW · HOW MUCH) **and the ready-to-paste NotebookLM prompt that closes the loop** |
| 7–8 Repair | `secondbrain/restudy.py` | Locating the fix inside the source |
| 11 Lifecycle | `secondbrain/lifecycle.py` | UNSEEN → LEARNING → WEAK → RELEARNING → STABLE → MASTERED → ARCHIVED, with reactivation on decline |
| — Analysis | `secondbrain/reports.py` | Daily / weekly / monthly / yearly analysis and the five deliverables (gap report, prescription, NotebookLM prompt, Anki update plan, mastery status) |
| 9–10 Re-test | `secondbrain/adaptive.py` | New questions only (old stems passed as forbidden), dynamic cognitive level |
| 11 Mastery | `secondbrain/mastery.py` | Six explicit criteria; nothing is "mastered" on one correct answer |
| 12 Archive | `secondbrain/notion.py` | Notion pages incl. *my historical weakness* and *how it was resolved*; Markdown fallback |
| Orchestration | `secondbrain/pipeline.py`, `secondbrain/cli.py` | One-call cycle, cron-friendly CLI, demo seed |
| Simple UI | `secondbrain/simple.py` | Phone-first prompts, three paste formats, plain-language weak spots |
| Chat analysis | `secondbrain/chat_analysis.py` | Paste a chat → NotebookLM checks claims against your sources, lists gaps, writes cards |

### The error taxonomy (`secondbrain/taxonomy.py`)

`FACTUAL_ERROR · CONCEPT_ERROR · DISCRIMINATION_ERROR · EXCEPTION_ERROR · THRESHOLD_ERROR ·
SEQUENCE_ERROR · INDICATION_ERROR · CONTRAINDICATION_ERROR · MONITORING_ERROR · MANAGEMENT_ERROR`

Plus detected signatures: repeated failure, knowledge gap, unstable retention, **false confidence**
(fast "Easy" followed by a lapse), **memorised-but-not-understood** (passes L1–L2, fails L4–L5) and
**understood-but-not-retrievable** (the reverse).

### Cognitive ladder

`L1 source & recall → L2 concept → L3 discrimination/boundaries → L4 clinical application → L5 integrated reasoning`

Difficulty adapts: a shaky lower layer pulls you back down; a solid layer pushes you up.

### The loop actually closes

Claude (or the built-in analysis) does not stop at “review SGLT2 inhibitors”. It writes the prompt
that goes **back into NotebookLM**:

```
LEARNING TARGET / KNOWLEDGE GAP / ERROR TYPE / SOURCE / SOURCE LOCATION /
LEARNING OBJECTIVE / STUDY DOSE / TASK: study only to close this gap …
```

so the next learning material is generated for that gap alone — minimum necessary learning,
maximum knowledge gain.

### Lifecycle

`UNSEEN → LEARNING → WEAK → RELEARNING → STABLE → MASTERED → ARCHIVED`

Archiving is never permanent: a decline on an archived unit **reactivates** it into RELEARNING, and
archived knowledge keeps being reviewed by Anki.

### Mastery criterion

A knowledge unit becomes `MASTERED` only when **all six** hold: ≥ 4 correct retrievals · spread over
≥ 21 days (or FSRS stability ≥ 21 d) · ≥ 2 different formulations · ≥ 1 correct at cognitive level ≥ 4 ·
last 3 reviews lapse-free · no unresolved error diagnosis.

---

## Free, phone-only setup

No server, no computer left on: host the hub on **Streamlit Community Cloud** (free), keep the
database alive in a **private GitHub repo**, and turn the loop by tapping **Sync**.
Full instructions: **[DEPLOY.md](DEPLOY.md)**.

Nothing runs on a schedule — by design. A free setup cannot honestly promise background jobs,
so the hub does everything in one tap: pull your Anki answers → score the knowledge gaps →
write at most three prescriptions → send new cards → back the database up.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the hub. Three sections sit on one page: **کارت‌سازی**, **ضعف‌ها**, **تحلیل چت**.
To watch the full loop on a seeded 60-day FSRS history: `python -m secondbrain.cli seed-demo`.

### Connections (all optional)

On Streamlit Cloud put keys in **App settings ▸ Secrets**. Locally, copy
`.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`, or run
`advanced/8_⚙️_Connections.py`, paste the keys, press *Save* and then *Test everything*.
The file is chmod 600 and git-ignored — no key ever needs to be typed into a chat.

| Service | API? | Used for |
|---|---|---|
| Claude | ✅ full API | diagnosing why the knowledge fails |
| Notion | ✅ full API | archiving mastered knowledge (optional — the hub already stores everything) |
| GitHub | ✅ contents API | free, persistent backup of the database |
| Anki | ✅ via your AnkiWeb account | pushing cards, pulling review history |
| Gemini | ✅ plain Gemini API | extraction and adaptive questions |
| **NotebookLM** | ❌ **no public API exists** | stays copy-and-paste — which is what keeps the answers grounded in *your* sources |

Or edit `.streamlit/secrets.toml` by hand:

```toml
GEMINI_API_KEY = "..."       # extraction + adaptive questions
ANTHROPIC_API_KEY = "..."    # Claude diagnostics
NOTION_TOKEN = "..."
NOTION_DATABASE_ID = "..."
ANKI_CONNECT_URL = "http://127.0.0.1:8765"
```

**Every stage works without API keys.** NotebookLM has no public API — and its source grounding is
exactly what we want — so each stage shows the exact prompt to paste into NotebookLM/Claude and
accepts the JSON reply back. The API path is a shortcut, never a requirement.

### 📱 From a phone (Chrome + AnkiDroid) — the intended workflow

The hub is mobile-first: single column, thumb-sized buttons, a big **Copy the prompt** button and a
direct link to NotebookLM.

**Option A — AnkiWeb sync (recommended, no computer needed)**

```toml
ANKIWEB_USERNAME = "your AnkiWeb e-mail"
ANKIWEB_PASSWORD = "your AnkiWeb password"
```

1. 📚 **Capture** — copy the prompt, paste it into your NotebookLM notebook, paste the JSON back.
2. 🔄 **Sync** — “Sync now”. The hub keeps its own Anki collection (`data/ankiweb/`), adds the new
   notes and syncs with AnkiWeb.
3. **AnkiDroid ▸ Sync** — the cards arrive on the phone. Study normally.
4. 🔄 **Sync now** again — your answers (revlog + FSRS stability/difficulty) come back into the hub.

A *full upload* would overwrite the collection on AnkiWeb, so the hub never does it implicitly:
a full-sync request is resolved by **downloading** your AnkiWeb collection first, and forcing an
upload requires typing `FULL UPLOAD`.

**Option B — file bridge (no account, nothing stored)**

1. 🔄 Sync ▸ *File (AnkiDroid)* ▸ **Build the deck file** ▸ download the `.apkg`.
2. Chrome ▸ Downloads ▸ tap the file ▸ open with **AnkiDroid**.
3. After studying: AnkiDroid ▸ Settings ▸ Advanced ▸ **Export collection** (with scheduling).
4. Upload that `.colpkg` back on the same tab — cards are matched by their `SecondBrainID` field,
   so renumbered notes still line up.

**Option C — desktop** — install the **AnkiConnect** add-on (code `2055492159`), keep Anki open and
use the 🖥 tab. The hub creates the deck `Second Brain::Medical` and the note type
`Second Brain Basic` (Question, Answer, Explanation, Source, KnowledgeUnit, SecondBrainID).

### CLI (cron-friendly)

```bash
python -m secondbrain.cli seed-demo        # sample collection
python -m secondbrain.cli cycle --pull     # pull reviews → profile → diagnose → plans → mastery
python -m secondbrain.cli profile          # the cumulative weakness profile
python -m secondbrain.cli plans            # today's targeted re-study plans
python -m secondbrain.cli sync             # AnkiWeb round trip (push cards, pull answers)
python -m secondbrain.cli push-anki        # transfer new cards over AnkiConnect
python -m secondbrain.cli import-reviews reviews.csv
python -m secondbrain.cli report weekly    # gap report + prescriptions + Anki plan + statuses
python -m secondbrain.cli mastery          # who is close, what is missing
python -m secondbrain.cli notion           # archive mastered units
```

---

## The one-page hub

`streamlit run app.py` opens **one page** with three sections (no jargon, phone-first).
The old multi-page UI lives in `advanced/` so Streamlit does **not** auto-load it.

| Section | Role |
|---|---|
| 🃏 کارت‌سازی | Topic → copy a short NotebookLM prompt → paste JSON / table / Q:A: → cards go to Anki |
| 🎯 ضعف‌ها | Pull Anki answers, show the top lapses in plain Persian, plus gaps found by chat analysis |
| 💬 تحلیل چت با NotebookLM | Paste a NotebookLM / Telegram / case chat → copy the analysis prompt → paste the JSON back → claims, gaps, cards |

Advanced pages (still there, run individually if you need them):
`advanced/1_📚_Sources.py` … `advanced/8_⚙️_Connections.py`.

Data lives in `data/second_brain.db` (SQLite, git-ignored). Exports land in `data/exports/`.

---

## راهنمای فارسی

این مخزن یک **مغز دوم پزشکی** است: یک حلقه‌ی بسته که مشخص می‌کند **چه چیزی را نمی‌دانی، چرا
نمی‌دانی، کجای منبع باید بازخوانی شود و از کجا بفهمیم واقعاً مسلط شده‌ای.**

هاب **یک صفحه** است با سه بخش: **کارت‌سازی**، **ضعف‌ها**، **تحلیل چت با NotebookLM**.
صفحات قدیمی به پوشهٔ `advanced/` منتقل شده‌اند تا Streamlit آن‌ها را خودکار نشان ندهد.

- منابع معتبر در **NotebookLM** بارگذاری می‌شوند؛ استخراج فقط از همان منابع انجام می‌شود و هر
  واحد دانشی که فصل/بخش/صفحه نداشته باشد **رد می‌شود**.
- کارت‌ها خودکار وارد آنکی می‌شوند: روی گوشی از طریق **سینک با AnkiWeb** (هاب یک کالکشن واقعی
  آنکی نگه می‌دارد و با حساب تو سینک می‌کند؛ در AnkiDroid فقط دکمه‌ی Sync را می‌زنی)، یا با
  فایل `.apkg`، یا روی دسکتاپ با **AnkiConnect**. تاریخچه‌ی مرور هم از همان مسیر برمی‌گردد.
- **FSRS** فقط حسگر است: می‌گوید «داری اشتباه می‌کنی»، نه «چرا».
- **Claude** با تحلیل طولی، نوع خطا را از میان ۱۰ دسته تعیین می‌کند و **پروفایل تجمعی ضعف**
  می‌سازد؛ الگو را می‌بیند، نه کارتِ تکی.
- سپس دقیقاً می‌گوید کدام جدول/الگوریتم/پاراگرافِ منبع را بخوانی و به چه چیزی توجه کنی
  (و فعلاً چه چیزی را نادیده بگیری).
- بعد از بازخوانی، **سؤال‌های تازه** (نه تکراری) در همان نقطه‌ضعف ساخته می‌شود تا معلوم شود
  فهمیده‌ای یا حفظ کرده‌ای.
- برچسب **MASTERED** فقط با تحقق هر شش معیار زده می‌شود، و دانشِ مسلط‌شده همراه با **تاریخچه‌ی
  ضعف و نحوه‌ی رفع آن** در **Notion** بایگانی می‌شود.

بدون هیچ کلید API هم کار می‌کند: در هر مرحله متن دقیق پرامپت را می‌دهد تا در NotebookLM یا Claude
بچسبانی و پاسخ JSON را برگردانی.
