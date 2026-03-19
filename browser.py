import asyncio
import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Optional emit callback — set by main.py before scraping
_emit = None

def set_emit(fn):
    global _emit
    _emit = fn

def emit(type: str, **kwargs):
    if _emit:
        _emit({"type": type, **kwargs})

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Chromium args — tuned for low-memory containerised envs (Render free tier ~512MB)
CHROMIUM_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
    "--disable-gpu", "--single-process", "--disable-extensions",
    "--disable-background-networking", "--disable-default-apps",
    "--disable-sync", "--disable-translate", "--hide-scrollbars",
    "--metrics-recording-only", "--mute-audio", "--no-first-run",
    "--safebrowsing-disable-auto-update", "--js-flags=--max-old-space-size=256",
]

async def _new_browser(p):
    return await p.chromium.launch(headless=True, args=CHROMIUM_ARGS, timeout=60000)


# ---------------------------------------------------------------------------
# Remotive — public JSON API
# ---------------------------------------------------------------------------
def scrape_remotive(query: str, max_results: int = 20) -> list[dict]:
    jobs = []
    emit("status", site="remotive", msg="Connecting to remotive.com API...")
    try:
        resp = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": query, "limit": max_results},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("jobs", [])
        emit("status", site="remotive", msg=f"Parsing {len(data)} listings...")
        for j in data[:max_results]:
            job = {
                "title": j.get("title", "N/A"),
                "company": j.get("company_name", "N/A"),
                "link": j.get("url", ""),
                "source": "remotive",
                "date": "",
            }
            jobs.append(job)
            emit("job", site="remotive", job=job)
    except Exception as e:
        emit("status", site="remotive", msg=f"Error: {e}", error=True)
    emit("status", site="remotive", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


# ---------------------------------------------------------------------------
# We Work Remotely — RSS feed
# ---------------------------------------------------------------------------
def scrape_weworkremotely(query: str, max_results: int = 20) -> list[dict]:
    jobs = []
    feeds = [
        "https://weworkremotely.com/remote-programming-jobs.rss",
        "https://weworkremotely.com/remote-jobs.rss",
    ]
    seen_links = set()
    kw = query.lower()
    emit("status", site="weworkremotely", msg="Fetching RSS feed...")
    for feed_url in feeds:
        try:
            resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title = item.findtext("title") or "N/A"
                link = item.findtext("link") or item.findtext("guid") or ""
                company_tag = item.find("{https://weworkremotely.com}company")
                company = company_tag.text if company_tag is not None else "N/A"
                if kw and kw not in title.lower() and kw not in (company or "").lower():
                    words = kw.split()
                    if not any(w in title.lower() for w in words):
                        continue
                if link not in seen_links:
                    seen_links.add(link)
                    job = {"title": title.strip(), "company": (company or "N/A").strip(),
                           "link": link, "source": "weworkremotely", "date": ""}
                    jobs.append(job)
                    emit("job", site="weworkremotely", job=job)
                if len(jobs) >= max_results:
                    break
        except Exception as e:
            emit("status", site="weworkremotely", msg=f"Feed error: {e}", error=True)
        if len(jobs) >= max_results:
            break
    emit("status", site="weworkremotely", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


# ---------------------------------------------------------------------------
# Adzuna — free API
# ---------------------------------------------------------------------------
def scrape_adzuna(query: str, max_results: int = 20, app_id: str = "", app_key: str = "", country: str = "gb") -> list[dict]:
    if not app_id or not app_key:
        return []
    jobs = []
    emit("status", site="adzuna", msg="Querying Adzuna API...")
    try:
        resp = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params={"app_id": app_id, "app_key": app_key,
                    "results_per_page": max_results, "what": query,
                    "content-type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        for j in resp.json().get("results", []):
            job = {
                "title": j.get("title", "N/A"),
                "company": j.get("company", {}).get("display_name", "N/A"),
                "link": j.get("redirect_url", ""),
                "source": "adzuna", "date": "",
            }
            jobs.append(job)
            emit("job", site="adzuna", job=job)
    except Exception as e:
        emit("status", site="adzuna", msg=f"Error: {e}", error=True)
    emit("status", site="adzuna", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


# ---------------------------------------------------------------------------
# MyJobMag Kenya — requests + BeautifulSoup (primary), Playwright fallback
# ---------------------------------------------------------------------------
MYJOBMAG_CATEGORIES = {
    "internship": "internships-volunteering", "intern": "internships-volunteering",
    "ict": "ict-computer", "it": "ict-computer", "software": "ict-computer",
    "developer": "ict-computer", "data": "ict-computer",
    "engineer": "engineering-technical",
    "finance": "finance-accounting-audit", "accounting": "finance-accounting-audit",
    "marketing": "sales-marketing-retail-business-development",
    "sales": "sales-marketing-retail-business-development",
    "hr": "human-resources-hr", "human resources": "human-resources-hr",
    "health": "medical-healthcare", "medical": "medical-healthcare",
    "ngo": "ngo-non-profit", "education": "education-teaching",
    "teaching": "education-teaching", "law": "law-legal", "legal": "law-legal",
    "logistics": "logistics", "graduate": "graduate-jobs", "entry level": "graduate-jobs",
}
BASE_URL = "https://www.myjobmag.co.ke"


def _parse_myjobmag_html(html: str, query: str, max_results: int) -> list[dict]:
    jobs = []
    kw_words = [w for w in query.lower().split() if len(w) > 3 and w not in
                ("jobs", "role", "position", "vacancy", "kenya", "nairobi", "remote")]
    soup = BeautifulSoup(html, "html.parser")
    for li in soup.select("ul.job-list > li"):
        try:
            title_el = li.select_one("li.mag-b h2 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            link = f"{BASE_URL}{href}" if href.startswith("/") else href
            company_img = li.select_one("li.job-logo img")
            company = (company_img.get("alt", "N/A") or "N/A").replace(" logo", "").strip() if company_img else "N/A"
            date_el = li.select_one("li#job-date")
            date = date_el.get_text(strip=True) if date_el else ""
            if kw_words and not any(w in title.lower() for w in kw_words):
                continue
            jobs.append({"title": title, "company": company, "link": link, "source": "myjobmag", "date": date})
            emit("job", site="myjobmag", job=jobs[-1])
            if len(jobs) >= max_results:
                break
        except Exception:
            continue
    return jobs


def scrape_myjobmag(query: str, max_results: int = 20) -> list[dict]:
    kw = query.lower()
    category = next((slug for word, slug in MYJOBMAG_CATEGORIES.items() if word in kw), None)
    url = f"{BASE_URL}/jobs-by-field/{category}" if category else f"{BASE_URL}/jobs"
    emit("status", site="myjobmag", msg=f"Fetching myjobmag.co.ke...")
    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        emit("status", site="myjobmag", msg="Parsing listings...")
        jobs = _parse_myjobmag_html(resp.text, query, max_results)
        if not jobs and category:
            emit("status", site="myjobmag", msg="No category results, trying main listing...")
            resp2 = requests.get(f"{BASE_URL}/jobs", headers=HEADERS, timeout=20)
            jobs = _parse_myjobmag_html(resp2.text, query, max_results)
    except Exception as e:
        emit("status", site="myjobmag", msg=f"Error: {e}", error=True)
    emit("status", site="myjobmag", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


# ---------------------------------------------------------------------------
# BrighterMonday Kenya — requests + BeautifulSoup (primary), Playwright fallback
# ---------------------------------------------------------------------------
BRIGHTERMONDAY_CATEGORIES = {
    "software": "software-data", "developer": "software-data", "data": "software-data",
    "ict": "software-data", "it": "software-data", "engineer": "engineering-manufacturing",
    "finance": "accounting-auditing-finance", "accounting": "accounting-auditing-finance",
    "marketing": "sales-marketing-retail-business-development",
    "sales": "sales-marketing-retail-business-development",
    "hr": "human-resources", "human resources": "human-resources",
    "health": "healthcare", "medical": "healthcare", "nurse": "healthcare",
    "ngo": "ngo-npo-charity", "nonprofit": "ngo-npo-charity",
    "education": "education", "teaching": "education",
    "law": "legal", "legal": "legal",
    "logistics": "logistics-transport-supply-chain",
    "internship": "internships", "intern": "internships",
    "graduate": "graduate-trainee", "entry level": "graduate-trainee",
    "admin": "admin-office", "secretary": "admin-office",
    "remote": "remote",
}
BM_BASE = "https://www.brightermonday.co.ke"


def _parse_brightermonday_html(html: str, query: str, max_results: int) -> list[dict]:
    jobs = []
    kw_words = [w for w in query.lower().split() if len(w) > 3 and w not in
                ("jobs", "role", "position", "vacancy", "kenya", "nairobi", "remote")]
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for a in soup.select('a[href*="/listings/"]'):
        try:
            title = a.get_text(strip=True)
            href = a.get("href", "")
            link = href if href.startswith("http") else f"{BM_BASE}{href}"
            if not title or len(title) < 3 or link in seen:
                continue
            seen.add(link)
            # walk up to find company/location context
            parent = a.parent
            for _ in range(5):
                if parent and parent.parent:
                    parent = parent.parent
                else:
                    break
            ctx_lines = [l.strip() for l in (parent.get_text("\n") if parent else "").split("\n") if l.strip()]
            company = ctx_lines[1] if len(ctx_lines) > 1 else "N/A"
            location = ctx_lines[2] if len(ctx_lines) > 2 else ""
            date_str = ""
            for line in reversed(ctx_lines):
                if re.search(r'\d+\s+(day|week|month|hour)s?\s+ago|^new$', line, re.I):
                    date_str = line
                    break
            display_date = location + (f" · {date_str}" if date_str else "")
            if kw_words and not any(w in title.lower() for w in kw_words):
                continue
            job = {"title": title, "company": company, "link": link,
                   "source": "brightermonday", "date": display_date.strip(" ·")}
            jobs.append(job)
            emit("job", site="brightermonday", job=job)
            if len(jobs) >= max_results:
                break
        except Exception:
            continue
    return jobs


def scrape_brightermonday(query: str, max_results: int = 20) -> list[dict]:
    kw = query.lower()
    category = next((slug for word, slug in BRIGHTERMONDAY_CATEGORIES.items() if word in kw), None)
    url = f"{BM_BASE}/jobs/{category}" if category else f"{BM_BASE}/jobs"
    emit("status", site="brightermonday", msg="Fetching brightermonday.co.ke...")
    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        emit("status", site="brightermonday", msg="Parsing listings...")
        jobs = _parse_brightermonday_html(resp.text, query, max_results)
        if not jobs:
            emit("status", site="brightermonday", msg="Trying Playwright fallback...")
            jobs = asyncio.run(_scrape_brightermonday_playwright(query, max_results))
    except Exception as e:
        emit("status", site="brightermonday", msg=f"Error: {e}", error=True)
    emit("status", site="brightermonday", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


async def _scrape_brightermonday_playwright(query: str, max_results: int) -> list[dict]:
    kw = query.lower()
    kw_words = [w for w in kw.split() if len(w) > 3 and w not in
                ("jobs", "role", "position", "vacancy", "kenya", "nairobi", "remote")]
    category = next((slug for word, slug in BRIGHTERMONDAY_CATEGORIES.items() if word in kw), None)
    url = f"{BM_BASE}/jobs/{category}" if category else f"{BM_BASE}/jobs"
    jobs = []
    seen_links = set()
    try:
        async with async_playwright() as p:
            browser = await _new_browser(p)
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=45000)
                await page.wait_for_timeout(4000)
                links = await page.query_selector_all('a[href*="/listings/"]')
                for lnk in links:
                    if len(jobs) >= max_results:
                        break
                    try:
                        title = (await lnk.inner_text()).strip()
                        href = await lnk.get_attribute("href") or ""
                        link = href if href.startswith("http") else f"{BM_BASE}{href}"
                        if not title or len(title) < 3 or link in seen_links:
                            continue
                        seen_links.add(link)
                        if kw_words and not any(w in title.lower() for w in kw_words):
                            continue
                        job = {"title": title, "company": "N/A", "link": link,
                               "source": "brightermonday", "date": ""}
                        jobs.append(job)
                        emit("job", site="brightermonday", job=job)
                    except Exception:
                        continue
            finally:
                await browser.close()
    except Exception as e:
        emit("status", site="brightermonday", msg=f"Playwright error: {e}", error=True)
    return jobs


# ---------------------------------------------------------------------------
# JobWebKenya — requests + BeautifulSoup (primary), Playwright fallback
# ---------------------------------------------------------------------------
JWK_BASE = "https://jobwebkenya.com"


def _parse_jobwebkenya_html(html: str, query: str, max_results: int) -> list[dict]:
    jobs = []
    kw_words = [w for w in query.lower().split() if len(w) > 3]
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for a in soup.select('a[href*="/jobs/"]'):
        try:
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) < 5 or href in seen:
                continue
            if any(x in href for x in ["facebook", "twitter", "linkedin", "sharer"]):
                continue
            seen.add(href)
            company = "N/A"
            if " at " in title:
                parts = title.rsplit(" at ", 1)
                title = parts[0].strip()
                company = parts[1].strip()
            if kw_words and not any(w in title.lower() or w in company.lower() for w in kw_words):
                continue
            job = {"title": title, "company": company, "link": href, "source": "jobwebkenya", "date": ""}
            jobs.append(job)
            emit("job", site="jobwebkenya", job=job)
            if len(jobs) >= max_results:
                break
        except Exception:
            continue
    return jobs


def scrape_jobwebkenya(query: str, max_results: int = 20) -> list[dict]:
    search_url = f"{JWK_BASE}/?s={query.replace(' ', '+')}"
    emit("status", site="jobwebkenya", msg="Fetching jobwebkenya.com...")
    jobs = []
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        emit("status", site="jobwebkenya", msg="Parsing listings...")
        jobs = _parse_jobwebkenya_html(resp.text, query, max_results)
        if not jobs:
            emit("status", site="jobwebkenya", msg="No search results, trying homepage...")
            resp2 = requests.get(JWK_BASE, headers=HEADERS, timeout=20)
            jobs = _parse_jobwebkenya_html(resp2.text, query, max_results)
        if not jobs:
            emit("status", site="jobwebkenya", msg="Trying Playwright fallback...")
            jobs = asyncio.run(_scrape_jobwebkenya_playwright(query, max_results))
    except Exception as e:
        emit("status", site="jobwebkenya", msg=f"Error: {e}", error=True)
    emit("status", site="jobwebkenya", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


async def _scrape_jobwebkenya_playwright(query: str, max_results: int) -> list[dict]:
    kw = query.lower()
    url = f"{JWK_BASE}/?s={query.replace(' ', '+')}"
    jobs = []
    try:
        async with async_playwright() as p:
            browser = await _new_browser(p)
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=45000)
                await page.wait_for_timeout(3000)
                html = await page.content()
                jobs = _parse_jobwebkenya_html(html, query, max_results)
            finally:
                await browser.close()
    except Exception as e:
        emit("status", site="jobwebkenya", msg=f"Playwright error: {e}", error=True)
    return jobs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def scrape_jobs(query: str, sites: list[str], max_results: int = 20, config: dict = None) -> list[dict]:
    config = config or {}
    all_jobs = []

    if "myjobmag" in sites:
        all_jobs.extend(scrape_myjobmag(query, max_results))
    if "brightermonday" in sites:
        all_jobs.extend(scrape_brightermonday(query, max_results))
    if "jobwebkenya" in sites:
        all_jobs.extend(scrape_jobwebkenya(query, max_results))
    if "remotive" in sites:
        all_jobs.extend(scrape_remotive(query, max_results))
    if "weworkremotely" in sites:
        all_jobs.extend(scrape_weworkremotely(query, max_results))
    if "adzuna" in sites:
        all_jobs.extend(scrape_adzuna(query, max_results,
            app_id=config.get("adzuna_app_id", ""),
            app_key=config.get("adzuna_app_key", ""),
            country=config.get("adzuna_country", "gb")))

    seen, unique = set(), []
    for job in all_jobs:
        if job["link"] and job["link"] not in seen:
            seen.add(job["link"])
            unique.append(job)
    return unique
