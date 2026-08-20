# Running the hub for free, with no computer left on

Goal: open the Second Brain from Chrome on your phone whenever you want, tap **Sync**, and have
nothing running the rest of the time.

```
your phone (Chrome)  →  hub on Streamlit Community Cloud   (free, always reachable)
                              │
                              ├─ AnkiWeb  ⇄  AnkiDroid      (free account you already have)
                              └─ private GitHub repo         (free, keeps the database alive)
```

Nothing is scheduled. The loop turns only when **you** tap Sync — which is exactly what a
zero-cost, zero-server setup can honestly promise.

---

## 1 · Deploy the hub (5 minutes, free)

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **New app** → pick this repository → branch `arena/01a01a7e-medical-app` → main file `app.py`.
3. Deploy. You get a permanent URL like `https://<name>.streamlit.app` — add it to your phone's
   home screen so it behaves like an app.

> If the build fails while installing `anki`, delete the `anki` line from `requirements.txt` and
> redeploy. Everything keeps working; you simply use the **File (AnkiDroid)** tab instead of
> AnkiWeb sync.

## 2 · Create the backup repository (this is the important one)

Free hosting **wipes its disk on every restart**. The database is only a few kilobytes, so we keep
it in a private repo.

1. On GitHub: **New repository** → name it e.g. `second-brain-data` → **Private**.
2. Create a token: [github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens)
   → *Fine-grained* → *Only select repositories* → `second-brain-data` →
   **Repository permissions ▸ Contents ▸ Read and write**.
3. In the hub: **⚙️ Connections** → paste the token and `yourname/second-brain-data` → **Save**.

From then on every Sync uploads the database, and a restarted host restores it automatically.

## 3 · Add the keys you actually want

| Key | Needed for | Free? |
|---|---|---|
| `ANKIWEB_USERNAME` / `ANKIWEB_PASSWORD` | cards to and answers from AnkiDroid | ✅ your own account |
| `GITHUB_TOKEN` / `GITHUB_REPO` | keeping the data alive | ✅ |
| `GEMINI_API_KEY` | automatic card writing (optional) | ✅ free tier |
| `ANTHROPIC_API_KEY` | automatic deep diagnosis (optional) | 💳 paid |

On Streamlit Cloud, put these in **App settings ▸ Secrets** (they survive restarts):

```toml
ANKIWEB_USERNAME = "you@example.com"
ANKIWEB_PASSWORD = "…"
GITHUB_TOKEN = "github_pat_…"
GITHUB_REPO = "yourname/second-brain-data"
```

The ⚙️ Connections page can also write them, but on a free host that file is temporary — the
Secrets box is the durable place.

## 4 · The daily rhythm

| When | You do | The hub does |
|---|---|---|
| New material | Capture → copy prompt → NotebookLM → paste JSON back | validates, keeps only traceable units |
| Any time | tap **Sync** | pulls your answers, scores the gaps, writes ≤ 3 prescriptions, sends new cards, backs up |
| Study | AnkiDroid, as usual | FSRS schedules everything |
| Weekly | open the report | patterns, chronic weaknesses, mastery changes |

Never more than **three** prescriptions per sync, and the home page shows **one**. A system that
hands you forty things to relearn is a system you will stop opening.

---

## راهنمای فارسی

**هدف:** هر وقت خواستی از کروم گوشی بازش کنی، **Sync** بزنی، و بقیه‌ی وقت هیچی روشن نباشه.

1. **میزبانی رایگان:** توی [share.streamlit.io](https://share.streamlit.io) با گیت‌هاب وارد شو،
   این ریپو و فایل `app.py` رو انتخاب کن. یه آدرس دائمی می‌گیری؛ اضافه‌ش کن به صفحه‌ی اصلی گوشی.
2. **پشتیبان (مهم‌ترین قدم):** هاست رایگان با هر ری‌استارت دیتاش پاک میشه. یه ریپوی
   **خصوصی** بساز، یه توکن با دسترسی Contents بگیر، و توی صفحه‌ی ⚙️ Connections واردش کن.
   از اون به بعد هر Sync دیتابیس رو ذخیره می‌کنه و اگه هاست پاک شد، خودکار برمی‌گردونه.
3. **کلیدها:** توی Streamlit Cloud برو App settings ▸ Secrets و همون‌جا بذارشون (ماندگارن).
   حداقلش: ایمیل/رمز AnkiWeb و توکن گیت‌هاب. کلید Gemini اختیاریه (رایگان)، Claude پولیه.
4. **ریتم روزانه:** منبع جدید → Capture؛ هر وقت خواستی → **Sync**؛ مطالعه → AnkiDroid؛
   هفتگی → گزارش.

هیچی خودکار در پس‌زمینه اجرا نمیشه — حلقه فقط وقتی می‌چرخه که **تو** Sync بزنی.
حداکثر **۳ نسخه** در هر سینک، و صفحه‌ی اول فقط **یکی** رو نشون میده.
