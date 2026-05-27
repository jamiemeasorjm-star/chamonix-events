#!/usr/bin/env python3
import httpx, json, re, sys, os
from datetime import date
from bs4 import BeautifulSoup

URL = "https://www.allocine.fr/seance/salle_gen_csalle=P1406.html"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")

MONTHS_FR = {"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}

def parse_french_date(text):
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.strip())
    if m:
        month = MONTHS_FR.get(m.group(2).lower())
        if month:
            return date(int(m.group(3)), month, int(m.group(1)))
    return None

def fetch():
    r = httpx.get(URL, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    venue = {"name":"Le Vox","address":"22, cours Bartavel, 74400"}
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string)
            if isinstance(d, dict) and d.get("@type")=="MovieTheater":
                venue["name"]=d.get("name",venue["name"])
                a=d.get("address",{})
                venue["address"]=f"{a.get("streetAddress","")}, {a.get("postalCode","")} {a.get("addressLocality","")}".strip(", ")
        except:
            pass
    events=[]
    for card in soup.find_all("div", class_="movie-card-theater"):
        title_el = card.find(["h2","h3"]) or card.find("a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        versions = card.find_all("div", class_="showtimes-version")
        showtimes = {}
        for ver in versions:
            for span in ver.find_all("span", attrs={"data-showtime-time": True}):
                iso = span["data-showtime-time"]
                dt = iso[:10]
                tm = iso[11:16]
                if dt not in showtimes:
                    showtimes[dt]=[]
                showtimes[dt].append(tm)
        if not showtimes:
            continue
        dates_sorted = sorted(showtimes.keys())
        img = card.find("img")
        image_url = img.get("src","") or img.get("data-src","") if img else ""
        if "acsta.net" in image_url:
            image_url = re.sub(r"/r_\d+_\d+/", "/r_640_/", image_url)
        events.append({
            "title": title,
            "description": f"Film screening at {venue["name"]}",
            "event_type": "cinema",
            "category": "Cinema",
            "source_url": URL,
            "image_url": image_url,
            "venue": venue["name"],
            "address": venue["address"],
            "commune": "Chamonix-Mont-Blanc",
            "start_date": dates_sorted[0],
            "end_date": dates_sorted[-1],
            "showtimes": showtimes,
            "language": "Francais"
        })
    return events, venue

def merge(existing, new_events):
    existing = [e for e in existing if e.get("category")!="Cinema"]
    existing.extend(new_events)
    return existing

def main():
    dry = "--dry-run" in sys.argv
    html = fetch()
    events, venue = parse(html)
    print(f"Found {len(events)} cinema events from {venue["name"]}")
    for ev in events:
        days=len(ev["showtimes"])
        total=sum(len(v) for v in ev["showtimes"].values())
        print(f"  {ev["title"]}: {days} days, {total} screenings")
    if dry:
        print("Dry run - no changes")
        return
    existing = []
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE) as f:
            existing = json.load(f)
    merged = merge(existing, events)
    with open(EVENTS_FILE, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"Merged: {len(existing)} -> {len(merged)} events")

if __name__ == "__main__":
    main()
