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
| 3 Transfer | `secondbrain/anki.py` | AnkiConnect client (deck + note type auto-created), `.apkg` fallback via genanki, review-log pull incl. FSRS memory state |
| 4 Sensor | `secondbrain/ingest.py` | Flexible CSV import of Anki revlog, local FSRS recomputation (`fsrs` package) |
| 5–6 Diagnosis | `secondbrain/diagnostics.py`, `secondbrain/claude.py` | Cumulative Weakness Profile, failure signatures, heuristic error hypotheses; longitudinal dossier + Claude prompt/parser |
| 7–8 Repair | `secondbrain/restudy.py` | Review targets inside the source and WHAT→WHERE→WHY→HOW plans |
| 9–10 Re-test | `secondbrain/adaptive.py` | New questions only (old stems passed as forbidden), dynamic cognitive level |
| 11 Mastery | `secondbrain/mastery.py` | Six explicit criteria; nothing is "mastered" on one correct answer |
| 12 Archive | `secondbrain/notion.py` | Notion pages incl. *my historical weakness* and *how it was resolved*; Markdown fallback |
| Orchestration | `secondbrain/pipeline.py`, `secondbrain/cli.py` | One-call cycle, cron-friendly CLI, demo seed |

### The error taxonomy (`secondbrain/taxonomy.py`)

`FACTUAL_ERROR · CONCEPT_ERROR · DISCRIMINATION_ERROR · EXCEPTION_ERROR · THRESHOLD_ERROR ·
SEQUENCE_ERROR · INDICATION_ERROR · CONTRAINDICATION_ERROR · MONITORING_ERROR · MANAGEMENT_ERROR`

Plus detected signatures: repeated failure, knowledge gap, unstable retention, **false confidence**
(fast "Easy" followed by a lapse), **memorised-but-not-understood** (passes L1–L2, fails L4–L5) and
**understood-but-not-retrievable** (the reverse).

### Cognitive ladder

`L1 source & recall → L2 concept → L3 discrimination/boundaries → L4 clinical application → L5 integrated reasoning`

Difficulty adapts: a shaky lower layer pulls you back down; a solid layer pushes you up.

### Mastery criterion

A knowledge unit becomes `MASTERED` only when **all six** hold: ≥ 4 correct retrievals · spread over
≥ 21 days (or FSRS stability ≥ 21 d) · ≥ 2 different formulations · ≥ 1 correct at cognitive level ≥ 4 ·
last 3 reviews lapse-free · no unresolved error diagnosis.

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the hub, press **“Load demo collection”** on the home page to watch the whole loop run on a
seeded 60-day FSRS history, then start replacing it with your own sources.

### Secrets (all optional)

Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`:

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

### Anki setup

1. Install the **AnkiConnect** add-on (code `2055492159`) and keep Anki open.
2. The hub creates the deck `Second Brain::Medical` and the note type `Second Brain Basic`
   (fields: Question, Answer, Explanation, Source, KnowledgeUnit, SecondBrainID).
3. If Anki runs on another machine: export `.apkg` from the Cards page and import the review log
   as CSV on the Performance page.

### CLI (cron-friendly)

```bash
python -m secondbrain.cli seed-demo        # sample collection
python -m secondbrain.cli cycle --pull     # pull reviews → profile → diagnose → plans → mastery
python -m secondbrain.cli profile          # the cumulative weakness profile
python -m secondbrain.cli plans            # today's targeted re-study plans
python -m secondbrain.cli push-anki        # transfer new cards
python -m secondbrain.cli import-reviews reviews.csv
python -m secondbrain.cli mastery          # who is close, what is missing
python -m secondbrain.cli notion           # archive mastered units
```

---

## Pages

| Page | Role |
|---|---|
| 🧠 Home | Loop status, cross-card patterns, today's priorities, one-button cycle |
| 📚 Sources | Register sources, run the grounded extraction, review what was rejected |
| 🃏 Anki Transfer | Push to Anki / build `.apkg` / browse every card and its generation |
| 📈 Performance | Pull the review log, import CSV, recompute FSRS state locally |
| 🔍 Diagnosis | Cumulative Weakness Profile + Claude's diagnostic engine + the taxonomy |
| 🎯 Re-study | WHAT → WHERE → WHY → HOW, with what to ignore for now |
| 🔁 Adaptive Questions | New formulations at the weakest cognitive layer |
| 🏆 Mastery & Notion | Six-criterion mastery check and the Notion archive |
| 💉 Clinical Tools | Tirzepatide Pen Master Calculator — the application layer |

Data lives in `data/second_brain.db` (SQLite, git-ignored). Exports land in `data/exports/`.

---

## راهنمای فارسی

این مخزن یک **مغز دوم پزشکی** است: یک حلقه‌ی بسته که مشخص می‌کند **چه چیزی را نمی‌دانی، چرا
نمی‌دانی، کجای منبع باید بازخوانی شود و از کجا بفهمیم واقعاً مسلط شده‌ای.**

- منابع معتبر در **NotebookLM** بارگذاری می‌شوند؛ استخراج فقط از همان منابع انجام می‌شود و هر
  واحد دانشی که فصل/بخش/صفحه نداشته باشد **رد می‌شود**.
- کارت‌ها با **AnkiConnect** خودکار وارد آنکی می‌شوند (بدون کپی‌پیست).
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
