# Tiko — AI Job Hunting Agent

**Live demo:** https://tiko-job-agent.onrender.com

Tiko is a local web app that scrapes multiple job boards simultaneously, streams results to your browser in real time, and lets you chat with an agent to search, filter, track, and export jobs — all without leaving one tab.

![Tiko UI](https://i.imgur.com/placeholder.png)

---

## What makes it different

Most job boards make you search each site separately, deal with duplicate listings, and manually track what you've applied to. Tiko does all of that in one place:

- **Live scraping** — watch Tiko open each site and pull jobs in real time via a split-pane UI
- **Chat interface** — type natural language commands instead of clicking through filters
- **Multi-source** — hits 5 job boards at once and deduplicates results
- **Recency-sorted** — jobs are automatically re-ordered newest first when scraping finishes
- **Application tracker** — mark jobs as Interested / Applied / Skip directly on the card
- **CSV export** — save results to open in Excel or Google Sheets

---

## Job sources

| Source | Type | Best for |
|---|---|---|
| [MyJobMag Kenya](https://www.myjobmag.co.ke) | Playwright (headless) | Internships, local Kenyan roles |
| [BrighterMonday](https://www.brightermonday.co.ke) | Playwright (headless) | Largest Kenyan board, 2000+ listings |
| [JobWebKenya](https://jobwebkenya.com) | Playwright (headless) | NGO, corporate, graduate roles |
| [Fuzu Kenya](https://www.fuzu.com/kenya/jobs) | HTML scraper | Kenyan & African roles, internships |
| [Remotive](https://remotive.com) | JSON API | Remote-first global tech jobs |
| [WeWorkRemotely](https://weworkremotely.com) | RSS feed | Remote programming & design jobs |

You can also add **Adzuna** (free API) by dropping your keys into `config.json`.

---

## Tech stack

- **Python 3.10+**
- **Flask** — lightweight local web server
- **Playwright** — headless Chromium for JS-rendered sites
- **Server-Sent Events (SSE)** — streams scraping progress to the UI in real time
- **Vanilla JS** — no React, no build step, just open and run

---

## Quick start

**1. Clone and set up a virtual environment**

```bash
git clone https://github.com/yourname/tiko-agent.git
cd tiko-agent
python3 -m venv venv
source venv/bin/activate
```

**2. Install dependencies**

```bash
pip3 install -r requirements.txt
```

**3. Install Chromium (one time only)**

```bash
playwright install chromium
```

**4. Run the app**

```bash
./main.py
```

> No virtual environment activation needed — the shebang points directly to the local venv.

**5. Open your browser**

```
http://localhost:5000
```

---

## Project structure

```
tiko-agent/
├── main.py           # Flask server + SSE streaming endpoint
├── agent.py          # Intent parser + task orchestrator
├── browser.py        # All scraper logic (Playwright + API + RSS)
├── config.json       # Sites, limits, optional API keys
├── requirements.txt
├── templates/
│   └── index.html    # Split-pane chat UI
├── static/
│   └── index.css     # All styles
└── results/          # Exported CSV files land here
```

---

## Chat commands

### Searching
```
find internship jobs in Kenya
search for data analyst roles in Nairobi
get me remote python developer jobs
find all junior frontend jobs in South Africa
look for UX designer positions in London
any machine learning jobs in Germany
find NGO jobs in Kenya
find graduate jobs in Nairobi
```

### Filtering results
```
filter only remote
filter by senior
only show full-time
narrow to React jobs
```

### Browsing
```
show jobs
show top 20
list all results
how many jobs did you find
```

### Tracking applications
```
mark 3 as applied
mark 5 as interested
skip job 2
show applied
show interested
```

### Opening jobs
```
open job 4          # opens in your browser
open top 5          # opens top 5 in browser tabs
```

### Sorting & summary
```
sort by company
sort by title
summary
```

### Saving
```
save
export results
```

### Other
```
clear               # reset everything
start over
help                # show all commands
```

---

## Configuration

Edit `config.json` to customise behaviour:

```json
{
  "job_titles": ["python developer", "backend engineer"],
  "locations": ["remote", "Nairobi", "Kenya"],
  "sites": ["myjobmag", "brightermonday", "jobwebkenya", "fuzu", "remotive", "weworkremotely"],
  "max_results_per_site": 20,
  "output_dir": "results",
  "adzuna_app_id": "",
  "adzuna_app_key": "",
  "adzuna_country": "gb"
}
```

| Key | Description |
|---|---|
| `sites` | Which sources to scrape. Remove any you don't need. |
| `max_results_per_site` | Cap per source per search. |
| `adzuna_app_id / app_key` | Free API keys from [developer.adzuna.com](https://developer.adzuna.com) |
| `adzuna_country` | Two-letter country code: `ke`, `gb`, `us`, etc. |

---

## Adding an AI API (optional)

Tiko is rule-based by default — no API key needed. If you want AI-powered job summarisation or smarter filtering, add your key to `config.json`:

```json
{
  "api_key": "sk-..."
}
```

Support for OpenAI / Groq can be wired into `agent.py` using the `api_key` field.

---

## How the live scraping works

When you type a search command:

1. The chat sends the query to `/search-stream` via **Server-Sent Events**
2. Flask spawns a background thread and starts scraping all configured sites
3. Each scraper emits `status` and `job` events as it works
4. The browser receives these events and renders job cards live in the left pane
5. When all scrapers finish, results are **re-sorted by recency** (newest first) and the counter updates

---

## Notes on scraping

- Tiko uses **polite scraping** — headless Chromium with natural page load delays
- LinkedIn and Indeed are intentionally excluded — they aggressively block scrapers
- If a site changes its HTML structure, update the relevant scraper in `browser.py`
- Results are deduplicated by URL across all sources

---

## License

MIT — do whatever you want with it.

---

Built with 🤖 by VIncent O. Adam
