"""Weather and venue source probe for the weekly game-day context layer (ADR-099).

Runs on a GitHub-hosted runner (``.github/workflows/source-probe-weather.yml``): the development
sandbox's egress policy denies ``api.weather.gov``, ``*.open-meteo.com``, ``*.wikipedia.org``
and ``www.wikidata.org`` (ADR-009 is the same situation for the Phase-0 probes).
Standard library only, so it needs no dependency install.

What it records, each as evidence a later decision cites:

1. **Venues.** For every stadium the 2017-2026 nflverse schedule names, the Wikipedia article
   (title, revision id and timestamp, the article's own coordinates), the linked Wikidata item
   and its ``P625`` coordinate (CC0), and every sentence of the article that mentions a roof.
   This is the provenance for ``config/venues.yaml``; nothing is assumed from memory.
2. **NWS.** For each U.S. venue: ``/points/{lat},{lon}``, then the ``forecastHourly`` and
   ``forecastGridData`` links it returns, with every unit, update time, generation time and
   valid interval, and the kickoff-hour values for the games in the next eight days.
3. **Open-Meteo forecast.** The same for each non-U.S. venue (and two U.S. venues, so the two
   providers can be compared at the same kickoff), including what an out-of-range kickoff
   returns.
4. **The forecast archive.** For games at open-air and retractable-roof venues in the declared
   seasons: Open-Meteo's Historical Forecast API (the first hours of each archived model run)
   and Previous Runs API (the forecast issued one and two days earlier), plus the ERA5
   reanalysis, each read at the kickoff hour. Joined later, offline, to the game-book weather
   nflverse records, this measures forecast-minus-recorded error at a known lead time.

Open-Meteo is used under its free non-commercial terms and attributed (CC BY 4.0); NWS data
is a U.S. Government work; Wikidata is CC0; Wikipedia text is quoted as evidence only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

USER_AGENT = "jeisey-tiers source probe (https://github.com/jeisey/jeisey-tiers)"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
EASTERN = ZoneInfo("America/New_York")

#: nflverse stadium id -> the Wikipedia article the probe resolves. ``country`` decides the
#: forecast provider (NWS inside the U.S., Open-Meteo elsewhere). A title is only a search key:
#: the probe records the article it actually resolved to, and a wrong guess shows up as a
#: mismatched name or coordinates in the evidence, not as a silent fact.
VENUES: tuple[dict[str, str], ...] = (
    {"stadium_id": "ATL97", "title": "Mercedes-Benz Stadium", "country": "US"},
    {"stadium_id": "BAL00", "title": "M&T Bank Stadium", "country": "US"},
    {"stadium_id": "BOS00", "title": "Gillette Stadium", "country": "US"},
    {"stadium_id": "BUF00", "title": "Highmark Stadium", "country": "US"},
    {"stadium_id": "BUF00-2026", "title": "New Highmark Stadium", "country": "US"},
    {"stadium_id": "CAR00", "title": "Bank of America Stadium", "country": "US"},
    {"stadium_id": "CHI98", "title": "Soldier Field", "country": "US"},
    {"stadium_id": "CIN00", "title": "Paycor Stadium", "country": "US"},
    {"stadium_id": "CLE00", "title": "Huntington Bank Field", "country": "US"},
    {"stadium_id": "DAL00", "title": "AT&T Stadium", "country": "US"},
    {"stadium_id": "DEN00", "title": "Empower Field at Mile High", "country": "US"},
    {"stadium_id": "DET00", "title": "Ford Field", "country": "US"},
    {"stadium_id": "FRA00", "title": "Deutsche Bank Park", "country": "DE"},
    {"stadium_id": "GER00", "title": "Allianz Arena", "country": "DE"},
    {"stadium_id": "GNB00", "title": "Lambeau Field", "country": "US"},
    {"stadium_id": "HOU00", "title": "NRG Stadium", "country": "US"},
    {"stadium_id": "IND00", "title": "Lucas Oil Stadium", "country": "US"},
    {"stadium_id": "JAX00", "title": "EverBank Stadium", "country": "US"},
    {"stadium_id": "KAN00", "title": "Arrowhead Stadium", "country": "US"},
    {"stadium_id": "LAX01", "title": "SoFi Stadium", "country": "US"},
    {"stadium_id": "LAX97", "title": "Dignity Health Sports Park", "country": "US"},
    {"stadium_id": "LAX99", "title": "Los Angeles Memorial Coliseum", "country": "US"},
    {"stadium_id": "LON00", "title": "Wembley Stadium", "country": "GB"},
    {"stadium_id": "LON01", "title": "Twickenham Stadium", "country": "GB"},
    {"stadium_id": "LON02", "title": "Tottenham Hotspur Stadium", "country": "GB"},
    {"stadium_id": "MAD01", "title": "Santiago Bernabéu Stadium", "country": "ES"},
    {"stadium_id": "MEL00", "title": "Melbourne Cricket Ground", "country": "AU"},
    {"stadium_id": "MEX00", "title": "Estadio Azteca", "country": "MX"},
    {"stadium_id": "MIA00", "title": "Hard Rock Stadium", "country": "US"},
    {"stadium_id": "MIN01", "title": "U.S. Bank Stadium", "country": "US"},
    {"stadium_id": "MUN01", "title": "Allianz Arena", "country": "DE"},
    {"stadium_id": "NAS00", "title": "Nissan Stadium", "country": "US"},
    {"stadium_id": "NOR00", "title": "Caesars Superdome", "country": "US"},
    {"stadium_id": "NYC01", "title": "MetLife Stadium", "country": "US"},
    {"stadium_id": "OAK00", "title": "Oakland Coliseum", "country": "US"},
    {"stadium_id": "PAR00", "title": "Stade de France", "country": "FR"},
    {"stadium_id": "PHI00", "title": "Lincoln Financial Field", "country": "US"},
    {"stadium_id": "PHO00", "title": "State Farm Stadium", "country": "US"},
    {"stadium_id": "PIT00", "title": "Acrisure Stadium", "country": "US"},
    {"stadium_id": "RIO00", "title": "Maracanã Stadium", "country": "BR"},
    {"stadium_id": "SAO00", "title": "Neo Química Arena", "country": "BR"},
    {"stadium_id": "SEA00", "title": "Lumen Field", "country": "US"},
    {"stadium_id": "SFO01", "title": "Levi's Stadium", "country": "US"},
    {"stadium_id": "TAM00", "title": "Raymond James Stadium", "country": "US"},
    {"stadium_id": "VEG00", "title": "Allegiant Stadium", "country": "US"},
    {"stadium_id": "WAS00", "title": "Northwest Stadium", "country": "US"},
)

#: A schedule row whose stadium name contradicts its stadium id is resolved by the name: the
#: 2026 file files a Jacksonville "home" game in London under ``JAX00``.
NAME_OVERRIDES: dict[str, str] = {
    "Tottenham Hotspur Stadium": "LON02",
    "Tottenham Stadium": "LON02",
}

#: Venues whose schedule roof is ever ``dome`` are skipped by the archive (no weather reaches
#: the field); everything else is fetched, including retractable roofs, whose outside weather
#: is the question when the roof state is not announced.
ROOF_SENTENCE = re.compile(
    r"[^.]*\b(retractable|roof|roofed|dome|domed|open[- ]air|indoor|enclosed|canopy)\b[^.]*\.",
    re.IGNORECASE,
)

HOURLY_VARIABLES = (
    "temperature_2m",
    "wind_speed_10m",
    "precipitation",
    "precipitation_probability",
)
UNITS = {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"}


class Fetcher:
    """One polite HTTP client: a descriptive User-Agent, a pause, bounded retries."""

    def __init__(self, pause: float) -> None:
        self.pause = pause
        self.calls: dict[str, int] = defaultdict(int)
        self.failures: list[dict[str, Any]] = []
        #: Hosts that answered 429 twice in a row: the probe stops asking them.
        self.exhausted: set[str] = set()

    def get(self, url: str, *, accept: str = "application/json") -> tuple[int, Any, dict[str, str]]:
        host = urllib.parse.urlparse(url).netloc
        last_error = ""
        if host in self.exhausted:
            self.failures.append({"url": url, "status": 429, "error": "host rate-limited; skipped"})
            return 429, None, {}
        limited = 0
        for attempt in range(4):
            self.calls[host] += 1
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": accept}
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = response.read()
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    time.sleep(self.pause)
                    if "json" in accept or body[:1] in (b"{", b"["):
                        return response.status, json.loads(body.decode("utf-8")), headers
                    return response.status, body.decode("utf-8"), headers
            except urllib.error.HTTPError as error:
                last_error = f"HTTP {error.code}"
                body = error.read()[:400].decode("utf-8", "replace")
                if error.code == 429:
                    limited += 1
                    if limited >= 2:
                        self.exhausted.add(host)
                        self.failures.append({"url": url, "status": 429, "body": body})
                        return 429, None, {}
                    time.sleep(65)
                    continue
                if error.code in (500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                self.failures.append({"url": url, "status": error.code, "body": body})
                time.sleep(self.pause)
                return error.code, None, {}
            except (urllib.error.URLError, TimeoutError) as error:
                last_error = str(error)
                time.sleep(2 ** (attempt + 1))
        self.failures.append({"url": url, "status": None, "error": last_error})
        return 0, None, {}


def kickoff_utc(gameday: str, gametime: str) -> datetime | None:
    if not gameday or not gametime:
        return None
    local = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M").replace(tzinfo=EASTERN)
    return local.astimezone(UTC)


def load_games(fetcher: Fetcher) -> list[dict[str, Any]]:
    status, text, _ = fetcher.get(GAMES_URL, accept="text/csv")
    if status != 200:
        raise SystemExit(f"could not read {GAMES_URL}: {status}")
    games: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        if row["game_type"] != "REG" or int(row["season"]) < 2017:
            continue
        stadium_id = NAME_OVERRIDES.get(row["stadium"], row["stadium_id"])
        if stadium_id == "BUF00" and int(row["season"]) >= 2026:
            stadium_id = "BUF00-2026"
        if stadium_id == "GER00" or stadium_id == "MUN01":
            stadium_id = "GER00"
        games.append(
            {
                "game_id": row["game_id"],
                "season": int(row["season"]),
                "week": int(row["week"]),
                "stadium_id": stadium_id,
                "schedule_stadium_id": row["stadium_id"],
                "stadium": row["stadium"],
                "roof": row["roof"] or None,
                "location": row["location"],
                "kickoff_utc": kickoff_utc(row["gameday"], row["gametime"]),
            },
        )
    return games


#: Venues the first run could not place, and the redirects and searches that place them. An
#: old name redirects to the article about the building that carried it, so a former name is
#: the strongest evidence of which article describes the 2017-2025 venue (``Highmark Stadium``
#: now describes Buffalo's 2026 building; ``Nissan Stadium``'s article has no coordinates).
RESOLVE: tuple[dict[str, Any], ...] = (
    {
        "stadium_id": "NAS00",
        "titles": (
            "Nissan Stadium",
            "Nissan Stadium (1999)",
            "Nissan Stadium (Nashville)",
            "LP Field",
            "LP Field (Nashville)",
            "Adelphia Coliseum",
            "The Coliseum (Nashville)",
        ),
        "search": "Tennessee Titans stadium Nashville opened 1999",
    },
    {
        "stadium_id": "BUF00",
        "titles": (
            "Highmark Stadium",
            "Highmark Stadium (1973)",
            "Highmark Stadium (Orchard Park)",
            "Ralph Wilson Stadium",
            "New Era Field",
            "Rich Stadium",
            "Bills Stadium",
        ),
        "search": "Buffalo Bills stadium Orchard Park opened 1973",
    },
)


#: Every stadium name the 2017-2026 schedule prints: each must redirect to the article (and
#: Wikidata item) of the venue the registry files it under, which is the alias's provenance.
#: For the venues nflverse's roof history cannot settle (international venues, a new building),
#: every sentence of the article about the roof, the pitch or the open air is kept as well.
SCHEDULE_NAMES: tuple[str, ...] = (
    "Allianz Arena (Munich)",
    "Football Arena Munich",
    "Munich Football Arena",
    "Tottenham Hotspur Stadium",
    "Azteca Stadium",
    "Bernabeu",
    "CenturyLink Field",
    "Deutsche Bank Park",
    "Estadio Banorte",
    "EverBank Field",
    "FC Bayern Munich Stadium",
    "FedExField",
    "FirstEnergy Stadium",
    "GEHA Field at Arrowhead Stadium",
    "Heinz Field",
    "Maracana Stadium",
    "Mercedes-Benz Superdome",
    "New Era Field",
    "Oakland-Alameda County Coliseum",
    "Paul Brown Stadium",
    "Reliant Stadium",
    "Ring Central Coliseum",
    "Sports Authority Field at Mile High",
    "StubHub Center",
    "TIAA Bank Stadium",
    "Tottenham Stadium",
    "University of Phoenix Stadium",
)
ROOF_EVIDENCE_TITLES: tuple[str, ...] = (
    "Allianz Arena",
    "Arena Corinthians",
    "Bernabéu (stadium)",
    "Estadio Azteca",
    "Highmark Stadium",
    "Maracanã Stadium",
    "Melbourne Cricket Ground",
    "Stade de France",
    "Tottenham Hotspur Stadium",
    "Twickenham Stadium",
    "Waldstadion (Frankfurt)",
    "Wembley Stadium",
    "Mercedes-Benz Stadium",
    "Reliant Stadium",
)
PITCH_SENTENCE = re.compile(
    r"[^.]*\b(retractable|roof\w*|dome\w*|open[- ]air|outdoor\w*|indoor\w*|enclosed|canopy|"
    r"uncovered|covers?|covered|elements|sky)\b[^.]*\.",
    re.IGNORECASE,
)


#: The two forecast providers' published terms, read on the day the sources are registered.
TERMS_PAGES: tuple[str, ...] = (
    "https://www.weather.gov/documentation/services-web-api",
    "https://api.weather.gov/openapi.json",
    "https://open-meteo.com/en/terms",
    "https://open-meteo.com/en/licence",
    "https://open-meteo.com/en/pricing",
    "https://open-meteo.com/en/docs/historical-forecast-api",
    "https://open-meteo.com/en/docs/previous-runs-api",
)
TERMS_SENTENCE = re.compile(
    r"[^.<>]*\b(user[- ]agent|rate limit\w*|limit\w*|commercial|attribution|attribute|"
    r"licen[cs]e\w*|CC[- ]BY|public domain|open data|free|10[,.]?000|calls?|cache\w*|"
    r"terms of (use|service)|archive\w*|initiali[sz]ed|lead time|model runs?)\b[^.<>]*[.]",
    re.IGNORECASE,
)


def probe_terms(fetcher: Fetcher) -> dict[str, Any]:
    """Status, headers and every sentence about use, limits, licence or archives, per page."""
    pages: dict[str, Any] = {}
    for url in TERMS_PAGES:
        status, body, headers = fetcher.get(url, accept="text/html,application/json")
        text = json.dumps(body) if isinstance(body, (dict, list)) else str(body or "")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())
        sentences: list[str] = []
        for match in TERMS_SENTENCE.finditer(text):
            sentence = match.group(0).strip()[:500]
            if sentence not in sentences:
                sentences.append(sentence)
        pages[url] = {
            "status": status,
            "last_modified": headers.get("last-modified"),
            "content_length": len(text),
            "sentences": sentences[:80],
        }
        print(f"terms {url}: {status} {len(sentences)} sentences", flush=True)
    return pages


def _wikitext(fetcher: Fetcher, title: str) -> str:
    """The article's full wikitext (redirects followed), for infobox fields and roof lines."""
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": title,
        },
    )
    _, payload, _ = fetcher.get(f"https://en.wikipedia.org/w/api.php?{query}")
    page = ((payload or {}).get("query") or {}).get("pages", [{}])[0] if payload else {}
    revision = (page.get("revisions") or [{}])[0]
    return str(((revision.get("slots") or {}).get("main") or {}).get("content") or "")


def probe_roof_evidence(fetcher: Fetcher) -> dict[str, Any]:
    """Schedule names' redirect targets, and roof/pitch sentences for unsettled venues."""
    names = {title: _page_record(fetcher, title) for title in SCHEDULE_NAMES}
    roofs: dict[str, Any] = {}
    for title in ROOF_EVIDENCE_TITLES:
        query = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "extracts|revisions|pageprops",
                "rvprop": "ids|timestamp",
                "explaintext": "1",
                "titles": title,
            },
        )
        status, payload, _ = fetcher.get(f"https://en.wikipedia.org/w/api.php?{query}")
        page = ((payload or {}).get("query") or {}).get("pages", [{}])[0] if payload else {}
        text = page.get("extract") or ""
        wikitext = _wikitext(fetcher, title)
        roofs[title] = {
            "infobox": {
                field: re.findall(rf"\|\s*{field}\s*=\s*([^\n]*)", wikitext)[:2]
                for field in ("roof", "type", "surface", "acreage", "field_shape")
            },
            "wikitext_roof_lines": [
                " ".join(line.split())[:300]
                for line in wikitext.splitlines()
                if re.search(r"\b(roof\w*|open[- ]air|retract\w*|canopy|uncovered)\b", line, re.I)
            ][:40],
            "wikipedia_status": status,
            "wikipedia_title": page.get("title"),
            "wikipedia_revid": (page.get("revisions") or [{}])[0].get("revid"),
            "wikidata_item": (page.get("pageprops") or {}).get("wikibase_item"),
            "sentences": [
                " ".join(match.group(0).split())[:400] for match in PITCH_SENTENCE.finditer(text)
            ][:40],
        }
        print(f"roof evidence {title}: {len(roofs[title]['sentences'])} sentences", flush=True)
    return {"schedule_names": names, "roof_evidence": roofs}


HATNOTE = re.compile(r"\{\{(?:About|For|Other uses|Distinguish|Redirect)[^}]*\}\}")
CLOSED = re.compile(r"\|\s*(?:closed|demolished)\s*=\s*([^\n|]*)")


def _page_record(fetcher: Fetcher, title: str) -> dict[str, Any]:
    """One title, redirects followed: the article, its coordinates, its lead and hatnotes."""
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
            "prop": "pageprops|coordinates|extracts|revisions",
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "rvsection": "0",
            "exintro": "1",
            "explaintext": "1",
            "titles": title,
        },
    )
    status, payload, _ = fetcher.get(f"https://en.wikipedia.org/w/api.php?{query}")
    record: dict[str, Any] = {"requested_title": title, "wikipedia_status": status}
    page = ((payload or {}).get("query") or {}).get("pages", [{}])[0] if payload else {}
    if not page or page.get("missing"):
        record["wikipedia_missing"] = True
        return record
    revision = (page.get("revisions") or [{}])[0]
    wikitext = (((revision.get("slots") or {}).get("main") or {}).get("content")) or ""
    record.update(
        {
            "wikipedia_title": page.get("title"),
            "wikipedia_pageid": page.get("pageid"),
            "wikipedia_revid": revision.get("revid"),
            "wikipedia_rev_timestamp": revision.get("timestamp"),
            "redirects": (payload.get("query") or {}).get("redirects"),
            "wikipedia_coordinates": [
                {"lat": c.get("lat"), "lon": c.get("lon"), "primary": c.get("primary")}
                for c in page.get("coordinates") or []
            ],
            "wikidata_item": (page.get("pageprops") or {}).get("wikibase_item"),
            "disambiguation": "disambiguation" in (page.get("pageprops") or {}),
            "lead": " ".join((page.get("extract") or "").split())[:900],
            "hatnotes": re.findall(HATNOTE, wikitext)[:6],
            "infobox_coordinates": re.findall(r"\{\{[Cc]oord\|[^}]*\}\}", wikitext)[:3],
            "infobox_opened": re.findall(r"\|\s*opened\s*=\s*([^\n|]*)", wikitext)[:2],
            "infobox_closed": re.findall(CLOSED, wikitext)[:2],
            "infobox_roof": re.findall(r"\|\s*roof\s*=\s*([^\n|]*)", wikitext)[:2],
        },
    )
    qid = record.get("wikidata_item")
    if qid:
        status, entity, _ = fetcher.get(
            f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        )
        node = ((entity or {}).get("entities") or {}).get(qid) or {}
        claims = node.get("claims") or {}
        record["wikidata_status"] = status
        record["wikidata_label"] = ((node.get("labels") or {}).get("en") or {}).get("value")
        record["wikidata_description"] = ((node.get("descriptions") or {}).get("en") or {}).get(
            "value"
        )
        record["wikidata_P625"] = [
            {
                "lat": value.get("latitude"),
                "lon": value.get("longitude"),
                "precision": value.get("precision"),
                "rank": claim.get("rank"),
            }
            for claim in claims.get("P625", [])
            for value in [((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}]
        ]
    return record


def probe_resolution(fetcher: Fetcher) -> dict[str, Any]:
    """Every candidate title and the top search hits for each venue in ``RESOLVE``."""
    resolved: dict[str, Any] = {}
    for target in RESOLVE:
        pages = [_page_record(fetcher, title) for title in target["titles"]]
        query = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "list": "search",
                "srlimit": "8",
                "srsearch": target["search"],
            },
        )
        status, payload, _ = fetcher.get(f"https://en.wikipedia.org/w/api.php?{query}")
        hits = [hit.get("title") for hit in ((payload or {}).get("query") or {}).get("search", [])]
        seen = {page.get("wikipedia_title") for page in pages}
        searched = [_page_record(fetcher, title) for title in hits if title not in seen][:5]
        resolved[target["stadium_id"]] = {
            "search": target["search"],
            "search_status": status,
            "search_hits": hits,
            "titles": pages,
            "searched": searched,
        }
        print(
            f"resolve {target['stadium_id']}: "
            + "; ".join(
                f"{page['requested_title']} -> {page.get('wikipedia_title')} "
                f"{page.get('wikidata_item')} {page.get('wikipedia_coordinates')}"
                for page in pages
            ),
            flush=True,
        )
    return resolved


# ---------------------------------------------------------------------------- venues


def probe_venues(fetcher: Fetcher) -> dict[str, dict[str, Any]]:
    venues: dict[str, dict[str, Any]] = {}
    for seed in VENUES:
        query = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "pageprops|coordinates|extracts|revisions",
                "rvprop": "ids|timestamp",
                "explaintext": "1",
                "titles": seed["title"],
            },
        )
        status, payload, _ = fetcher.get(f"https://en.wikipedia.org/w/api.php?{query}")
        record: dict[str, Any] = {**seed, "wikipedia_status": status}
        page = ((payload or {}).get("query") or {}).get("pages", [{}])[0] if payload else {}
        if page and not page.get("missing"):
            text = page.get("extract") or ""
            record.update(
                {
                    "wikipedia_title": page.get("title"),
                    "wikipedia_pageid": page.get("pageid"),
                    "wikipedia_revid": (page.get("revisions") or [{}])[0].get("revid"),
                    "wikipedia_rev_timestamp": (page.get("revisions") or [{}])[0].get("timestamp"),
                    "wikipedia_coordinates": [
                        {"lat": c.get("lat"), "lon": c.get("lon"), "primary": c.get("primary")}
                        for c in page.get("coordinates") or []
                    ],
                    "wikidata_item": (page.get("pageprops") or {}).get("wikibase_item"),
                    "roof_sentences": [
                        " ".join(match.group(0).split())[:400]
                        for match in ROOF_SENTENCE.finditer(text)
                    ][:12],
                    "redirects": (payload.get("query") or {}).get("redirects"),
                },
            )
        else:
            record["wikipedia_missing"] = True
        qid = record.get("wikidata_item")
        if qid:
            status, entity, _ = fetcher.get(
                f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
            )
            claims = (((entity or {}).get("entities") or {}).get(qid) or {}).get("claims") or {}
            coordinates = []
            for claim in claims.get("P625", []):
                value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
                coordinates.append(
                    {
                        "lat": value.get("latitude"),
                        "lon": value.get("longitude"),
                        "precision": value.get("precision"),
                        "rank": claim.get("rank"),
                    },
                )
            label = (
                (((entity or {}).get("entities") or {}).get(qid) or {}).get("labels") or {}
            ).get("en", {})
            record.update(
                {
                    "wikidata_status": status,
                    "wikidata_label": label.get("value"),
                    "wikidata_P625": coordinates,
                    "wikidata_P17": [
                        (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}).get(
                            "id"
                        )
                        for c in claims.get("P17", [])
                    ],
                },
            )
        venues[seed["stadium_id"]] = record
        print(
            f"venue {seed['stadium_id']}: {record.get('wikipedia_title')} "
            f"{record.get('wikidata_item')} P625={record.get('wikidata_P625')}",
            flush=True,
        )
    return venues


def coordinates(venue: dict[str, Any]) -> tuple[float, float] | None:
    for claim in venue.get("wikidata_P625") or []:
        if claim.get("lat") is not None and claim.get("rank") != "deprecated":
            return float(claim["lat"]), float(claim["lon"])
    for item in venue.get("wikipedia_coordinates") or []:
        if item.get("lat") is not None:
            return float(item["lat"]), float(item["lon"])
    return None


# ---------------------------------------------------------------------------- forecasts


def _interval(valid_time: str) -> tuple[datetime, datetime]:
    """An ISO-8601 ``start/duration`` interval as NWS publishes it (``PT1H``, ``P1DT6H``)."""
    start_text, duration = valid_time.split("/")
    start = datetime.fromisoformat(start_text)
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration)
    if not match:
        raise ValueError(valid_time)
    days, hours, minutes = (int(value or 0) for value in match.groups())
    return start, start + timedelta(days=days, hours=hours, minutes=minutes)


def _grid_value(layer: dict[str, Any] | None, at: datetime) -> dict[str, Any] | None:
    if not layer:
        return None
    for item in layer.get("values") or []:
        start, end = _interval(item["validTime"])
        if start <= at < end:
            return {
                "value": item.get("value"),
                "valid_time": item["validTime"],
                "uom": layer.get("uom"),
            }
    return {"value": None, "valid_time": None, "uom": layer.get("uom"), "out_of_range": True}


def probe_nws(
    fetcher: Fetcher, venue_id: str, lat: float, lon: float, games: list[dict[str, Any]]
) -> dict[str, Any]:
    point_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
    status, point, headers = fetcher.get(point_url, accept="application/geo+json")
    result: dict[str, Any] = {"venue": venue_id, "points_url": point_url, "points_status": status}
    if not point:
        return result
    properties = point.get("properties") or {}
    result["points"] = {
        key: properties.get(key)
        for key in (
            "gridId",
            "gridX",
            "gridY",
            "forecast",
            "forecastHourly",
            "forecastGridData",
            "timeZone",
            "radarStation",
        )
    }
    result["points"]["relativeLocation"] = (properties.get("relativeLocation") or {}).get(
        "properties"
    ) or {}
    result["points_cache_control"] = headers.get("cache-control")
    hourly_status, hourly, hourly_headers = fetcher.get(
        properties["forecastHourly"], accept="application/geo+json"
    )
    grid_status, grid, grid_headers = fetcher.get(
        properties["forecastGridData"], accept="application/geo+json"
    )
    result["hourly_status"] = hourly_status
    result["grid_status"] = grid_status
    result["hourly_headers"] = {
        k: hourly_headers.get(k) for k in ("cache-control", "expires", "last-modified")
    }
    result["grid_headers"] = {
        k: grid_headers.get(k) for k in ("cache-control", "expires", "last-modified")
    }
    periods: list[dict[str, Any]] = []
    if hourly:
        hp = hourly.get("properties") or {}
        periods = hp.get("periods") or []
        result["hourly"] = {
            "updateTime": hp.get("updateTime"),
            "generatedAt": hp.get("generatedAt"),
            "validTimes": hp.get("validTimes"),
            "units": hp.get("units"),
            "elevation": hp.get("elevation"),
            "periods": len(periods),
            "first_period": periods[0] if periods else None,
            "last_end": periods[-1].get("endTime") if periods else None,
            "period_keys": sorted(periods[0]) if periods else [],
        }
    gp = (grid or {}).get("properties") or {}
    if grid:
        result["grid"] = {
            "updateTime": gp.get("updateTime"),
            "validTimes": gp.get("validTimes"),
            "elevation": gp.get("elevation"),
            "layers": {
                name: {
                    "uom": (gp.get(name) or {}).get("uom"),
                    "values": len((gp.get(name) or {}).get("values") or []),
                }
                for name in (
                    "temperature",
                    "windSpeed",
                    "windGust",
                    "probabilityOfPrecipitation",
                    "quantitativePrecipitation",
                    "skyCover",
                    "weather",
                )
            },
        }
    kickoffs = []
    for game in games:
        at = game["kickoff_utc"]
        period = next(
            (
                p
                for p in periods
                if datetime.fromisoformat(p["startTime"])
                <= at
                < datetime.fromisoformat(p["endTime"])
            ),
            None,
        )
        kickoffs.append(
            {
                "game_id": game["game_id"],
                "kickoff_utc": at.isoformat(),
                "hourly": None
                if period is None
                else {
                    key: period.get(key)
                    for key in (
                        "startTime",
                        "endTime",
                        "temperature",
                        "temperatureUnit",
                        "windSpeed",
                        "windDirection",
                        "probabilityOfPrecipitation",
                        "shortForecast",
                    )
                },
                "grid": {
                    name: _grid_value(gp.get(name), at)
                    for name in (
                        "temperature",
                        "windSpeed",
                        "windGust",
                        "probabilityOfPrecipitation",
                        "quantitativePrecipitation",
                    )
                }
                if grid
                else None,
            },
        )
    result["kickoffs"] = kickoffs
    return result


def probe_open_meteo(
    fetcher: Fetcher, venue_id: str, lat: float, lon: float, games: list[dict[str, Any]]
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "hourly": ",".join((*HOURLY_VARIABLES, "wind_gusts_10m")),
            "timezone": "GMT",
            "forecast_days": "16",
            **UNITS,
        },
    )
    url = f"https://api.open-meteo.com/v1/forecast?{query}"
    status, payload, headers = fetcher.get(url)
    result: dict[str, Any] = {"venue": venue_id, "url": url, "status": status}
    if not payload:
        return result
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    result.update(
        {
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "elevation": payload.get("elevation"),
            "generationtime_ms": payload.get("generationtime_ms"),
            "timezone": payload.get("timezone"),
            "hourly_units": payload.get("hourly_units"),
            "first_time": times[0] if times else None,
            "last_time": times[-1] if times else None,
            "hours": len(times),
            "headers": {k: headers.get(k) for k in ("cache-control", "date", "last-modified")},
        },
    )
    kickoffs = []
    for game in games:
        key = game["kickoff_utc"].replace(minute=0).strftime("%Y-%m-%dT%H:%M")
        if key in times:
            index = times.index(key)
            values = {
                name: (hourly.get(name) or [None])[index] for name in hourly if name != "time"
            }
            kickoffs.append(
                {
                    "game_id": game["game_id"],
                    "kickoff_utc": game["kickoff_utc"].isoformat(),
                    "hour": key,
                    **values,
                }
            )
        else:
            kickoffs.append(
                {
                    "game_id": game["game_id"],
                    "kickoff_utc": game["kickoff_utc"].isoformat(),
                    "out_of_range": True,
                }
            )
    result["kickoffs"] = kickoffs
    return result


# ---------------------------------------------------------------------------- archive

ARCHIVE_APIS = {
    "hf": ("https://historical-forecast-api.open-meteo.com/v1/forecast", HOURLY_VARIABLES),
    "pr": (
        "https://previous-runs-api.open-meteo.com/v1/forecast",
        tuple(
            f"{name}_previous_day{day}"
            for day in (1, 2)
            for name in ("temperature_2m", "wind_speed_10m", "precipitation")
        ),
    ),
    "era5": (
        "https://archive-api.open-meteo.com/v1/archive",
        ("temperature_2m", "wind_speed_10m", "precipitation"),
    ),
}


def _write_archive(out: Path, rows: dict[str, dict[str, Any]]) -> None:
    if not rows:
        return
    ordered = [rows[key] for key in sorted(rows)]
    columns = sorted({key for row in ordered for key in row}, key=lambda k: (k != "game_id", k))
    with (out / "archive_games.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(ordered)


def probe_archive(
    fetcher: Fetcher,
    venues: dict[str, dict[str, Any]],
    games: list[dict[str, Any]],
    seasons: list[int],
    *,
    out: Path,
    deadline: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    dome_ids = {game["stadium_id"] for game in games if game["roof"] == "dome"}
    by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        if game["season"] in seasons and game["stadium_id"] not in dome_ids and game["kickoff_utc"]:
            by_key[(game["stadium_id"], game["season"])].append(game)
    rows: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []
    truncated = False
    for (venue_id, season), venue_games in sorted(
        by_key.items(), key=lambda item: (-item[0][1], item[0][0])
    ):
        if time.monotonic() > deadline:
            truncated = True
            break
        venue = venues.get(venue_id) or {}
        point = coordinates(venue)
        if point is None:
            continue
        start = min(g["kickoff_utc"] for g in venue_games).date()
        end = (max(g["kickoff_utc"] for g in venue_games) + timedelta(hours=4)).date()
        for tag, (base, variables) in ARCHIVE_APIS.items():
            query = urllib.parse.urlencode(
                {
                    "latitude": f"{point[0]:.4f}",
                    "longitude": f"{point[1]:.4f}",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "hourly": ",".join(variables),
                    "timezone": "GMT",
                    **UNITS,
                },
            )
            status, payload, _ = fetcher.get(f"{base}?{query}")
            hourly = (payload or {}).get("hourly") or {}
            times = hourly.get("time") or []
            index = {value: position for position, value in enumerate(times)}
            calls.append(
                {
                    "api": tag,
                    "venue": venue_id,
                    "season": season,
                    "status": status,
                    "hours": len(times),
                    "units": (payload or {}).get("hourly_units"),
                },
            )
            for game in venue_games:
                row = rows.setdefault(
                    game["game_id"],
                    {
                        "game_id": game["game_id"],
                        "season": game["season"],
                        "week": game["week"],
                        "venue": venue_id,
                        "schedule_roof": game["roof"],
                        "kickoff_utc": game["kickoff_utc"].strftime("%Y-%m-%dT%H:%MZ"),
                    },
                )
                hour = game["kickoff_utc"].replace(minute=0)
                position = index.get(hour.strftime("%Y-%m-%dT%H:%M"))
                for name in variables:
                    series = hourly.get(name) or []
                    value = (
                        series[position]
                        if position is not None and position < len(series)
                        else None
                    )
                    row[f"{tag}_{name}"] = value
                if "precipitation" in variables and position is not None:
                    window = (hourly.get("precipitation") or [])[position : position + 3]
                    present = [value for value in window if value is not None]
                    row[f"{tag}_precipitation_3h"] = round(sum(present), 3) if present else None
            print(f"archive {tag} {venue_id} {season}: {status} {len(times)}h", flush=True)
        _write_archive(out, rows)
        (out / "archive_calls.json").write_text(json.dumps(calls, indent=2) + "\n")
    return [rows[key] for key in sorted(rows)], calls, truncated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=0.6)
    parser.add_argument("--archive-seasons", default="2022,2023,2024,2025")
    parser.add_argument("--horizon-days", type=int, default=17)
    parser.add_argument("--archive-budget-minutes", type=float, default=25.0)
    parser.add_argument(
        "--phases",
        choices=("all", "resolve"),
        default="all",
        help="'resolve' runs only the venue-resolution phase (venue_resolution.json)",
    )
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(args.pause)
    started = datetime.now(UTC)

    if args.phases == "resolve":
        resolution = probe_resolution(fetcher)
        resolution["_run"] = {
            "started_at_utc": started.isoformat(),
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "user_agent": USER_AGENT,
            "calls_by_host": dict(fetcher.calls),
            "failures": fetcher.failures,
        }
        resolution.update(probe_roof_evidence(fetcher))
        resolution["terms"] = probe_terms(fetcher)
        resolution["_run"]["calls_by_host"] = dict(fetcher.calls)
        resolution["_run"]["finished_at_utc"] = datetime.now(UTC).isoformat()
        (out / "venue_resolution.json").write_text(
            json.dumps(resolution, indent=2, ensure_ascii=False) + "\n"
        )
        return 0

    games = load_games(fetcher)
    venues = probe_venues(fetcher)
    (out / "venues.json").write_text(json.dumps(venues, indent=2, ensure_ascii=False) + "\n")

    upcoming = [
        game
        for game in games
        if game["kickoff_utc"]
        and started <= game["kickoff_utc"] <= started + timedelta(days=args.horizon_days)
    ]
    by_venue: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for game in upcoming:
        by_venue[game["stadium_id"]].append(game)
    nws: list[dict[str, Any]] = []
    meteo: list[dict[str, Any]] = []
    countries = {seed["stadium_id"]: seed["country"] for seed in VENUES}
    compare_us = {"BUF00-2026", "CHI98"}
    for venue_id, venue_games in sorted(by_venue.items()):
        point = coordinates(venues.get(venue_id) or {})
        if point is None:
            print(f"no coordinates for {venue_id}", flush=True)
            continue
        if countries.get(venue_id) == "US":
            nws.append(probe_nws(fetcher, venue_id, *point, venue_games))
            if venue_id in compare_us:
                meteo.append(probe_open_meteo(fetcher, venue_id, *point, venue_games))
        else:
            meteo.append(probe_open_meteo(fetcher, venue_id, *point, venue_games))
    # Every non-U.S. venue at least once, so the schema is recorded even with no game ahead.
    for seed in VENUES:
        if seed["country"] != "US" and seed["stadium_id"] not in by_venue:
            point = coordinates(venues.get(seed["stadium_id"]) or {})
            if point is not None and seed["stadium_id"] in {"LON00", "PAR00", "MAD01", "MEX00"}:
                meteo.append(probe_open_meteo(fetcher, seed["stadium_id"], *point, []))
    (out / "nws.json").write_text(json.dumps(nws, indent=2, default=str) + "\n")
    (out / "open_meteo_forecast.json").write_text(json.dumps(meteo, indent=2, default=str) + "\n")

    seasons = [int(value) for value in args.archive_seasons.split(",") if value]
    deadline = time.monotonic() + 60.0 * args.archive_budget_minutes
    archive, calls, truncated = probe_archive(
        fetcher, venues, games, seasons, out=out, deadline=deadline
    )
    summary = {
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "user_agent": USER_AGENT,
        "calls_by_host": dict(fetcher.calls),
        "failures": fetcher.failures,
        "venues": len(venues),
        "venues_without_coordinates": sorted(
            k for k, v in venues.items() if coordinates(v) is None
        ),
        "upcoming_games": len(upcoming),
        "nws_venues": len(nws),
        "open_meteo_venues": len(meteo),
        "archive_games": len(archive),
        "archive_seasons": seasons,
        "archive_truncated_by_budget": truncated,
        "rate_limited_hosts": sorted(fetcher.exhausted),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
