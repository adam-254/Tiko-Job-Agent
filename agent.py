import re
import json
import csv
import os
import webbrowser
from datetime import datetime
from browser import scrape_jobs

with open("config.json") as f:
    CONFIG = json.load(f)

# In-memory job store for the session
_jobs: list[dict] = []
_tracker: dict[int, str] = {}  # index -> status: "interested" | "applied" | "skip"


def _save_results(jobs: list[dict], filename: str = None) -> str:
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    if not filename:
        filename = f"{CONFIG['output_dir']}/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "company", "link", "source", "date"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(jobs)
    return filename


def get_jobs() -> list[dict]:
    return _jobs


def _do_search(query: str) -> list[dict]:
    """Called by the SSE route to run a search and populate _jobs."""
    global _jobs, _tracker
    sites = CONFIG.get("sites", ["myjobmag", "remotive", "weworkremotely"])
    max_r = CONFIG.get("max_results_per_site", 20)
    _jobs = scrape_jobs(query, sites, max_r, config=CONFIG)
    _tracker = {}
    return _jobs


def _format_job(i: int, j: dict) -> str:
    status = f" [{_tracker[i].upper()}]" if i in _tracker else ""
    return f"{i+1}.{status} {j['title']} @ {j['company']} — {j['source']}\n   {j['link']}"


def parse_and_run(user_input: str) -> str:
    global _jobs, _tracker
    text = user_input.lower().strip()

    # --- SEARCH intent ---
    # handles: find / search / look for / get / show me / any <role> jobs in <location>
    trigger_words = ["find", "search", "look for", "get me", "get", "show me", "any"]
    if any(kw in text for kw in trigger_words):
        # strip the trigger word first
        cleaned = text
        for kw in sorted(trigger_words, key=len, reverse=True):
            cleaned = re.sub(rf"^{re.escape(kw)}\s+(me\s+)?(all\s+)?", "", cleaned).strip()
            if cleaned != text.strip():
                break

        # split on " in " to extract location
        location = None
        if " in " in cleaned:
            parts = cleaned.rsplit(" in ", 1)
            cleaned = parts[0].strip()
            location = parts[1].strip()

        # strip trailing job-type noise words to get the role
        role = re.sub(r"\s*(jobs?|positions?|roles?|openings?|listings?|internships?|vacancies?)$", "", cleaned).strip()
        if not role:
            role = cleaned  # fallback: use whatever is left

        query = f"{role} {location}".strip() if location else role
        try:
            _do_search(query)
        except Exception as e:
            return f"Scraping failed: {e}"
        if not _jobs:
            return f"No jobs found for '{query}'. Try a different keyword or location."
        filename = _save_results(_jobs)
        return f"Found {len(_jobs)} jobs for '{query}'. Saved to {filename}.\nType 'show jobs' to browse them."

    # --- FILTER intent ---
    # handles: filter only remote / filter senior / filter by python / only show full-time
    filter_match = re.search(r"(filter|only show|narrow|show only)\s+(by\s+|only\s+)?(.+)", text)
    if filter_match:
        if not _jobs:
            return "No jobs loaded yet. Search for something first."
        keyword = filter_match.group(3).strip()
        filtered = [
            j for j in _jobs
            if keyword in j["title"].lower()
            or keyword in j["company"].lower()
            or keyword in j.get("source", "").lower()
        ]
        if not filtered:
            return f"No jobs matched '{keyword}'. Try a broader keyword."
        _jobs = filtered
        _tracker = {new_i: _tracker[old_i] for new_i, old_i in enumerate(
            [i for i, j in enumerate(_jobs) if j in filtered]
        ) if old_i in _tracker}
        return f"Filtered to {len(_jobs)} jobs matching '{keyword}'."

    # --- COUNT intent ---
    if re.search(r"how many|count|total", text):
        if not _jobs:
            return "No jobs loaded yet."
        return f"There are {len(_jobs)} jobs in the current list."

    # --- SHOW / LIST intent ---
    show_match = re.search(r"(show|list|display|view)\s*(jobs?|results?|all|top\s*(\d+))?", text)
    if show_match:
        if not _jobs:
            return "No jobs loaded yet. Try: find internship jobs in Kenya"
        limit_match = re.search(r"top\s*(\d+)", text)
        limit = int(limit_match.group(1)) if limit_match else 10
        lines = [_format_job(i, j) for i, j in enumerate(_jobs[:limit])]
        suffix = f"\n...and {len(_jobs)-limit} more. Type 'show all' or 'show top 50'." if len(_jobs) > limit else ""
        return "\n".join(lines) + suffix

    # --- OPEN in browser intent ---
    open_match = re.search(r"open\s+(job\s+)?#?(\d+)", text)
    if open_match:
        idx = int(open_match.group(2)) - 1
        if 0 <= idx < len(_jobs):
            webbrowser.open(_jobs[idx]["link"])
            return f"Opening: {_jobs[idx]['title']} @ {_jobs[idx]['company']}"
        return f"No job #{idx+1} in the list."

    # open top N
    open_top_match = re.search(r"open\s+top\s+(\d+)", text)
    if open_top_match:
        n = min(int(open_top_match.group(1)), len(_jobs))
        for j in _jobs[:n]:
            webbrowser.open(j["link"])
        return f"Opened top {n} jobs in your browser."

    # --- MARK / TRACK intent ---
    # handles: mark 3 as applied / interested in job 5 / skip job 2
    mark_match = re.search(r"(mark|set|tag)\s+#?(\d+)\s+as\s+(applied|interested|skip|skipped)", text)
    if mark_match:
        idx = int(mark_match.group(2)) - 1
        status = mark_match.group(3).replace("skipped", "skip")
        if 0 <= idx < len(_jobs):
            _tracker[idx] = status
            return f"Marked job #{idx+1} ({_jobs[idx]['title']}) as '{status}'."
        return f"No job #{idx+1} found."

    interested_match = re.search(r"(interested in|apply to|skip)\s+job\s+#?(\d+)", text)
    if interested_match:
        action_map = {"interested in": "interested", "apply to": "applied", "skip": "skip"}
        action = next(v for k, v in action_map.items() if k in text)
        idx = int(interested_match.group(2)) - 1
        if 0 <= idx < len(_jobs):
            _tracker[idx] = action
            return f"Marked job #{idx+1} as '{action}'."
        return f"No job #{idx+1} found."

    # --- SHOW TRACKED intent ---
    if re.search(r"show (applied|interested|skipped?)", text):
        status_match = re.search(r"show (applied|interested|skipped?)", text)
        status = status_match.group(1).replace("skipped", "skip")
        tracked = [(i, _jobs[i]) for i in _tracker if _tracker[i] == status and i < len(_jobs)]
        if not tracked:
            return f"No jobs marked as '{status}' yet."
        lines = [_format_job(i, j) for i, j in tracked]
        return f"Jobs marked as '{status}':\n" + "\n".join(lines)

    # --- SORT intent ---
    if re.search(r"sort by (title|company|source)", text):
        sort_match = re.search(r"sort by (title|company|source)", text)
        key = sort_match.group(1)
        _jobs = sorted(_jobs, key=lambda j: j.get(key, "").lower())
        return f"Sorted {len(_jobs)} jobs by {key}."

    # --- SUMMARY intent ---
    if re.search(r"summary|summarize|overview|breakdown", text):
        if not _jobs:
            return "No jobs loaded yet."
        from collections import Counter
        sources = Counter(j["source"] for j in _jobs)
        breakdown = "\n".join(f"  {s}: {c} jobs" for s, c in sources.most_common())
        applied = sum(1 for s in _tracker.values() if s == "applied")
        interested = sum(1 for s in _tracker.values() if s == "interested")
        skipped = sum(1 for s in _tracker.values() if s == "skip")
        return (
            f"Total jobs: {len(_jobs)}\n"
            f"By source:\n{breakdown}\n"
            f"Tracked — Applied: {applied} | Interested: {interested} | Skipped: {skipped}"
        )

    # --- SAVE / EXPORT intent ---
    if re.search(r"save|export", text):
        if not _jobs:
            return "Nothing to save yet."
        filename = _save_results(_jobs)
        return f"Saved {len(_jobs)} jobs to {filename}"

    # --- CLEAR / RESET intent ---
    if re.search(r"clear|reset|start over|new search", text):
        _jobs = []
        _tracker = {}
        return "Cleared. Ready for a new search."

    # --- HELP ---
    if re.search(r"^help$|^what can you do|^commands|\?$", text):
        return (
            "Here's what you can ask me:\n\n"
            "SEARCHING\n"
            "  find internship jobs in Kenya\n"
            "  search for data analyst roles in Nairobi\n"
            "  get me remote python developer jobs\n"
            "  find all junior frontend jobs in South Africa\n"
            "  look for UX designer positions in London\n"
            "  any machine learning jobs in Germany\n\n"
            "BROWSING RESULTS\n"
            "  show jobs\n"
            "  show top 20\n"
            "  list all results\n"
            "  how many jobs did you find\n\n"
            "FILTERING\n"
            "  filter only remote\n"
            "  filter by senior\n"
            "  only show full-time\n"
            "  narrow to React jobs\n\n"
            "TRACKING APPLICATIONS\n"
            "  mark 3 as applied\n"
            "  mark 5 as interested\n"
            "  skip job 2\n"
            "  show applied\n"
            "  show interested\n\n"
            "OPENING JOBS\n"
            "  open job 4\n"
            "  open top 5\n\n"
            "SORTING & SUMMARY\n"
            "  sort by company\n"
            "  sort by title\n"
            "  summary\n\n"
            "SAVING\n"
            "  save\n"
            "  export results\n\n"
            "OTHER\n"
            "  clear\n"
            "  start over\n"
            "  help"
        )

    return "I didn't quite get that. Type 'help' to see everything I can do."
