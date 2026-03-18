import asyncio
import requests
import xml.etree.ElementTree as ET
from playwright.async_api import async_playwright

# Optional emit callback — set by main.py before scraping
_emit = None

def set_emit(fn):
    global _emit
    _emit = fn

def emit(type: str, **kwargs):
    if _emit:
        _emit({"type": type, **kwargs})


# ---------------------------------------------------------------------------
# Remotive — public JSON API
# ---------------------------------------------------------------------------
def scrape_remotive(query: str, max_results: int = 20) -> list[dict]:
    jobs = []
    emit("status", site="remotive", msg=f"Connecting to remotive.com API...")
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
# MyJobMag Kenya — Playwright scraper
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


async def _scrape_myjobmag_page(page, url: str, query: str, max_results: int) -> list[dict]:
    jobs = []
    kw = query.lower()
    kw_words = [w for w in kw.split() if len(w) > 3 and w not in
                ("jobs", "role", "position", "vacancy", "kenya", "nairobi", "remote")]
    emit("status", site="myjobmag", msg=f"Navigating to {url}")
    try:
        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(3000)
        items = await page.query_selector_all("ul.job-list > li")
        emit("status", site="myjobmag", msg=f"Found {len(items)} listings, filtering for '{query}'...")
        for item in items[:max_results * 2]:
            try:
                title_el = await item.query_selector("li.mag-b h2 a")
                company_img = await item.query_selector("li.job-logo img")
                date_el = await item.query_selector("li#job-date")
                if not title_el:
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href") or ""
                link = f"{BASE_URL}{href}" if href.startswith("/") else href
                company = (await company_img.get_attribute("alt") or "N/A").replace(" logo", "").strip() if company_img else "N/A"
                date = (await date_el.inner_text()).strip() if date_el else ""
                if kw_words and not any(w in title.lower() for w in kw_words):
                    continue
                job = {"title": title, "company": company, "link": link,
                       "source": "myjobmag", "date": date}
                jobs.append(job)
                emit("job", site="myjobmag", job=job)
                if len(jobs) >= max_results:
                    break
            except Exception:
                continue
    except Exception as e:
        emit("status", site="myjobmag", msg=f"Page error: {e}", error=True)
    return jobs


async def _scrape_myjobmag_async(query: str, max_results: int) -> list[dict]:
    kw = query.lower()
    category = next((slug for word, slug in MYJOBMAG_CATEGORIES.items() if word in kw), None)
    emit("status", site="myjobmag", msg="Launching headless Chromium...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            url = f"{BASE_URL}/jobs-by-field/{category}" if category else f"{BASE_URL}/jobs"
            jobs = await _scrape_myjobmag_page(page, url, query, max_results)
            if not jobs:
                emit("status", site="myjobmag", msg="No category match, trying main listing...")
                jobs = await _scrape_myjobmag_page(page, f"{BASE_URL}/jobs", query, max_results)
        finally:
            await browser.close()
    emit("status", site="myjobmag", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


def scrape_myjobmag(query: str, max_results: int = 20) -> list[dict]:
    try:
        return asyncio.run(_scrape_myjobmag_async(query, max_results))
    except Exception as e:
        emit("status", site="myjobmag", msg=f"Fatal error: {e}", error=True)
        return []


# ---------------------------------------------------------------------------
# BrighterMonday Kenya — Playwright scraper
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


async def _scrape_brightermonday_async(query: str, max_results: int) -> list[dict]:
    kw = query.lower()
    # extract meaningful keywords (skip short/noise words)
    kw_words = [w for w in kw.split() if len(w) > 3 and w not in
                ("jobs", "role", "position", "vacancy", "kenya", "nairobi", "remote")]

    category = next((slug for word, slug in BRIGHTERMONDAY_CATEGORIES.items() if word in kw), None)
    url = f"{BM_BASE}/jobs/{category}" if category else f"{BM_BASE}/jobs"

    emit("status", site="brightermonday", msg="Launching headless Chromium...")
    jobs = []
    seen_links = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            emit("status", site="brightermonday", msg=f"Navigating to {url}")
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(4000)
            links = await page.query_selector_all('a[href*="/listings/"]')
            emit("status", site="brightermonday", msg=f"Found {len(links)} listings, filtering for '{query}'...")

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

                    # get depth-5 context: has company, location, type, date
                    context = await lnk.evaluate('''el => {
                        let p = el;
                        for(let i=0;i<5;i++){ p = p.parentElement; if(!p) break; }
                        return p ? p.innerText.trim() : "";
                    }''')
                    lines = [l.strip() for l in context.split("\n") if l.strip()]

                    # lines[0]=title, [1]=company, [2]=location, [3]=type, [4]=salary/confidential
                    # date is the last line matching "X days/weeks/months ago" or "New"
                    import re
                    date_str = ""
                    for line in reversed(lines):
                        if re.search(r'\d+\s+(day|week|month|hour)s?\s+ago|^new$', line, re.I):
                            date_str = line
                            break

                    company  = lines[1] if len(lines) > 1 else "N/A"
                    location = lines[2] if len(lines) > 2 else ""
                    job_type = lines[3] if len(lines) > 3 else ""
                    display_date = f"{location} · {job_type}" + (f" · {date_str}" if date_str else "")

                    # keyword relevance filter — if we have keywords, at least one must match title
                    if kw_words and not any(w in title.lower() for w in kw_words):
                        continue

                    job = {"title": title, "company": company, "link": link,
                           "source": "brightermonday", "date": display_date.strip(" ·")}
                    jobs.append(job)
                    emit("job", site="brightermonday", job=job)
                except Exception:
                    continue
        except Exception as e:
            emit("status", site="brightermonday", msg=f"Error: {e}", error=True)
        finally:
            await browser.close()
    emit("status", site="brightermonday", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


def scrape_brightermonday(query: str, max_results: int = 20) -> list[dict]:
    try:
        return asyncio.run(_scrape_brightermonday_async(query, max_results))
    except Exception as e:
        emit("status", site="brightermonday", msg=f"Fatal: {e}", error=True)
        return []


# ---------------------------------------------------------------------------
# JobWebKenya — Playwright scraper (WordPress, clean link structure)
# ---------------------------------------------------------------------------
JWK_BASE = "https://jobwebkenya.com"


async def _scrape_jobwebkenya_async(query: str, max_results: int) -> list[dict]:
    kw = query.lower()
    # JWK uses /?s= for search
    url = f"{JWK_BASE}/?s={query.replace(' ', '+')}"
    emit("status", site="jobwebkenya", msg="Launching headless Chromium...")
    jobs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            emit("status", site="jobwebkenya", msg=f"Searching jobwebkenya.com for '{query}'...")
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(3000)
            links = await page.query_selector_all('a[href*="/jobs/"]')
            # filter out social share links
            emit("status", site="jobwebkenya", msg=f"Found {len(links)} links, filtering...")
            seen = set()
            for lnk in links:
                try:
                    title = (await lnk.inner_text()).strip()
                    href = await lnk.get_attribute("href") or ""
                    if not title or len(title) < 5 or href in seen:
                        continue
                    if any(x in href for x in ["facebook", "twitter", "linkedin", "sharer"]):
                        continue
                    seen.add(href)
                    # parse "Title at Company" pattern
                    company = "N/A"
                    if " at " in title:
                        parts = title.rsplit(" at ", 1)
                        title_clean = parts[0].strip()
                        company = parts[1].strip()
                    else:
                        title_clean = title
                    # keyword filter
                    words = [w for w in kw.split() if len(w) > 3]
                    if words and not any(w in title_clean.lower() or w in company.lower() for w in words):
                        continue
                    job = {"title": title_clean, "company": company,
                           "link": href, "source": "jobwebkenya", "date": ""}
                    jobs.append(job)
                    emit("job", site="jobwebkenya", job=job)
                    if len(jobs) >= max_results:
                        break
                except Exception:
                    continue
            # fallback: if search returned nothing, scrape homepage listings
            if not jobs:
                emit("status", site="jobwebkenya", msg="No search results, trying homepage...")
                await page.goto(JWK_BASE, timeout=25000)
                await page.wait_for_timeout(3000)
                links2 = await page.query_selector_all('a[href*="/jobs/"]')
                seen2 = set()
                for lnk in links2:
                    try:
                        title = (await lnk.inner_text()).strip()
                        href = await lnk.get_attribute("href") or ""
                        if not title or len(title) < 5 or href in seen2:
                            continue
                        if any(x in href for x in ["facebook", "twitter", "sharer"]):
                            continue
                        seen2.add(href)
                        company = "N/A"
                        if " at " in title:
                            parts = title.rsplit(" at ", 1)
                            title = parts[0].strip()
                            company = parts[1].strip()
                        job = {"title": title, "company": company,
                               "link": href, "source": "jobwebkenya", "date": ""}
                        jobs.append(job)
                        emit("job", site="jobwebkenya", job=job)
                        if len(jobs) >= max_results:
                            break
                    except Exception:
                        continue
        except Exception as e:
            emit("status", site="jobwebkenya", msg=f"Error: {e}", error=True)
        finally:
            await browser.close()
    emit("status", site="jobwebkenya", msg=f"Done — {len(jobs)} jobs found.", done=True)
    return jobs


def scrape_jobwebkenya(query: str, max_results: int = 20) -> list[dict]:
    try:
        return asyncio.run(_scrape_jobwebkenya_async(query, max_results))
    except Exception as e:
        emit("status", site="jobwebkenya", msg=f"Fatal: {e}", error=True)
        return []


# ---------------------------------------------------------------------------
# Playwright fallback for remotive
# ---------------------------------------------------------------------------
async def _scrape_remotive_browser(query: str, max_results: int) -> list[dict]:
    jobs = []
    url = f"https://remotive.com/remote-jobs?search={query.replace(' ', '+')}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(3000)
            items = await page.query_selector_all("li.job-list-item, .job-card")
            for item in items[:max_results]:
                try:
                    title_el = await item.query_selector("h2, h3, [class*='title']")
                    company_el = await item.query_selector("[class*='company']")
                    link_el = await item.query_selector("a")
                    title = (await title_el.inner_text()).strip() if title_el else "N/A"
                    company = (await company_el.inner_text()).strip() if company_el else "N/A"
                    href = await link_el.get_attribute("href") if link_el else ""
                    link = f"https://remotive.com{href}" if href and href.startswith("/") else href
                    if title != "N/A":
                        job = {"title": title, "company": company, "link": link,
                               "source": "remotive", "date": ""}
                        jobs.append(job)
                        emit("job", site="remotive", job=job)
                except Exception:
                    continue
        except Exception as e:
            emit("status", site="remotive", msg=f"Browser fallback error: {e}", error=True)
        finally:
            await browser.close()
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
        jobs = scrape_remotive(query, max_results)
        if not jobs:
            jobs = asyncio.run(_scrape_remotive_browser(query, max_results))
        all_jobs.extend(jobs)
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
