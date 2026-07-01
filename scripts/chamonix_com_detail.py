#!/usr/bin/env python3
"""Scrape chamonix.com event detail pages with Playwright."""

import json, os, sys, re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
LISTING_URL = "https://www.chamonix.com/evenements/evenements-et-manifestations"


def get_listing_urls(page):
    page.goto(LISTING_URL, wait_until="networkidle")
    soup = BeautifulSoup(page.content(), "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "/evenements-et-manifestations/" in h or "/animations-et-evenements-" in h:
            if h not in urls:
                urls.append(h)
    return urls


def extract_detail(page, url):
    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
    except PwTimeout:
        return {}
    soup = BeautifulSoup(page.content(), "html.parser")
    result = {}

    h1 = soup.find("h1")
    if h1:
        result["title"] = h1.get_text(strip=True)

    desc_parts = []
    for div in soup.find_all("div", class_="content-body"):
        text = div.get_text(strip=True)
        if text and len(text) > 10:
            desc_parts.append(text)
    if desc_parts:
        result["description"] = "\\n".join(desc_parts)

    img = soup.find("img", src=lambda s: s and "/sit/images/" in s if s else None)
    if img:
        src = img.get("src", "")
        if src:
            result["image_url"] = "https://www.chamonix.com" + src if src.startswith("/") else src

    for div in soup.find_all("div", class_="onglet-content"):
        t = div.get_text(strip=True)
        m = re.search(r"\d{2}/\d{2}/\d{4}", t)
        if m:
            parts = m.group(0).split("/")
            iso = f"{parts[2]}-{parts[1]}-{parts[0]}"
            if "start_date" not in result or iso < result["start_date"]:
                result["start_date"] = iso
            if "end_date" not in result or iso > result["end_date"]:
                result["end_date"] = iso

    time_el = soup.find(string=re.compile(r"\d{1,2}h\d{2}"))
    if time_el:
        m2 = re.search(r"\d{1,2}h\d{2}", str(time_el))
        if m2:
            result["time"] = m2.group(0)

    ville = soup.find(["span", "div"], class_="ville")
    if ville:
        result["commune"] = ville.get_text(strip=True).replace("a ", "").strip()

    addr = soup.find("div", class_="adresse")
    if addr:
        result["address"] = addr.get_text(strip=True)

    return result


def merge(existing, new_details):
    detail_map = {}
    for d in new_details:
        t = d.get("title", "").strip().lower()
        if t:
            detail_map[t] = d
    updated = 0
    for e in existing:
        key = e.get("title", "").strip().lower()
        if key in detail_map:
            d = detail_map[key]
            for field in ["description", "image_url", "time", "commune", "address"]:
                if field in d and d[field] and not e.get(field):
                    e[field] = d[field]
            for field in ["start_date", "end_date"]:
                if field in d and not e.get(field):
                    e[field] = d[field]
            updated += 1
    return existing, updated


def main():
    dry_run = "--dry-run" in sys.argv
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        urls = get_listing_urls(page)
        print(f"Found {len(urls)} event URLs")
        details = []
        for i, url in enumerate(urls, 1):
            slug = url.split("/")[-1][:40]
            print(f"  [{i}/{len(urls)}] {slug}...")
            detail = extract_detail(page, url)
            if detail:
                details.append(detail)
                dlen = len(detail.get("description", ""))
                has_img = bool(detail.get("image_url"))
                dt = detail.get("start_date", "?")
                print(f"    desc={dlen}c img={has_img} date={dt}")
            else:
                print(f"    No data")
        browser.close()

    print(f"Extracted {len(details)}/{len(urls)} detail pages")
    if dry_run:
        for d in details[:5]:
            title = d.get("title","?")
            desc = d.get("description","")[:100]
            image = "Y" if d.get("image_url") else "N"
            start = d.get("start_date","?")
            end = d.get("end_date","?")
            print(f"  {title}")
            print(f"    desc: {desc}")
            print(f"    image: {image}")
            print(f"    dates: {start} -> {end}")
        return

    with open(EVENTS_FILE) as f:
        existing = json.load(f)
    merged, updated = merge(existing, details)
    with open(EVENTS_FILE, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"Merged: {updated} events updated, total {len(merged)}")

if __name__ == "__main__":
    main()
