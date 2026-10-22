"""Readable case references: REGION-DISTRICT-COMMUNITY-NUMBER-YEAR, e.g. NR-TML-GUM-0012-2026.

The real case ID stays the long case_uuid (unique even when workers are offline);
the reference is for people: easy to read, say on the phone and search. No names.

    region     two letters, as in field workers' IDs (NR, OT, ...)
    district   first letter + next consonants of the main name (Tamale -> TML),
               plus N/S/E/W for a direction; "Municipal"/"Metropolitan" left out
    community  first 3 letters (Gumani -> GUM)
    number     counts the cases from that place, starting again each year

Codes start from data/place_codes.json (editable by hand). A place not in the list
gets a code by the same rule the first time it appears; the code is saved and marked
"not yet checked" for an administrator. A code is never changed once it has been used.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import psycopg

PLACE_CODES_FILE = Path("data/place_codes.json")
DIRECTIONS = {"North": "N", "South": "S", "East": "E", "West": "W"}
LEFT_OUT = {"Municipal", "Metropolitan"}


# 1. THE RULES
def consonant_code(word: str) -> str:
    """First letter, then the next consonants: Tamale -> TML, Savelugu -> SVL, Wa -> WA."""
    letters = re.sub(r"[^A-Za-z]", "", word).upper()
    code = letters[0] + "".join(ch for ch in letters[1:] if ch not in "AEIOU")
    return code[:3] if len(code) >= 3 else letters[:3]


def district_code(name: str) -> str:
    """Tamale Metropolitan -> TML; Nkwanta North -> NKWN; East Gonja -> GNJE."""
    words = [w for w in re.split(r"[ /-]+", name) if w not in LEFT_OUT]
    direction = "".join(DIRECTIONS[w] for w in words if w in DIRECTIONS)
    main = next((w for w in words if w not in DIRECTIONS), words[0])
    return consonant_code(main) + (direction if len(direction) == 1 else "")


def community_code(name: str) -> str:
    """Gumani -> GUM."""
    return re.sub(r"[^A-Za-z]", "", name).upper()[:3]


RULES = {"region": lambda name: consonant_code(name.replace("_", " "))[:2],
         "district": district_code, "community": community_code}


# 2. CODES IN THE DATABASE
def load_place_codes(connection: psycopg.Connection, path: Path = PLACE_CODES_FILE) -> None:
    """Copy the hand-checked list into the database. Codes already there are kept."""
    codes = json.loads(path.read_text())
    rows = [("region", name, "", code) for name, code in codes["regions"].items()]
    rows += [("district", name, "", code) for name, code in codes["districts"].items()]
    rows += [("community", name, district, code)
             for district, places in codes["communities"].items() for name, code in places.items()]
    for kind, name, district, code in rows:
        connection.execute(
            "INSERT INTO place_codes (kind, name, district, code, checked) VALUES (%s, %s, %s, %s, TRUE) "
            "ON CONFLICT DO NOTHING", (kind, name, district, code))


def place_code(connection: psycopg.Connection, kind: str, name: str, district: str = "") -> str:
    """The code for a place; a new place gets one by the rule, saved as "not yet checked"."""
    found = connection.execute("SELECT code FROM place_codes WHERE kind = %s AND name = %s AND district = %s",
                               (kind, name, district)).fetchone()
    if found:
        return found["code"] if isinstance(found, dict) else found[0]

    base = RULES[kind](name)
    taken = {row["code"] if isinstance(row, dict) else row[0] for row in connection.execute(
        "SELECT code FROM place_codes WHERE kind = %s AND district = %s", (kind, district))}
    code, n = base, 2
    while code in taken:                          # same code in the same district: add a number
        code, n = f"{base}{n}", n + 1
    connection.execute("INSERT INTO place_codes (kind, name, district, code, checked) "
                       "VALUES (%s, %s, %s, %s, FALSE)", (kind, name, district, code))
    return code


# 3. THE REFERENCE
def case_year(received_at: str | datetime | date | None) -> int:
    """The year the case was received (this year if unknown)."""
    if isinstance(received_at, (datetime, date)):
        return received_at.year
    match = re.match(r"(\d{4})", str(received_at or ""))
    return int(match.group(1)) if match else date.today().year


def case_reference(connection: psycopg.Connection, region: str | None, district: str | None,
                   community: str | None, received_at: str | datetime | None) -> str:
    """Next reference for a place and year, e.g. NR-TML-GUM-0012-2026."""
    parts = [place_code(connection, "region", region or "unknown")]
    if district:
        parts.append(place_code(connection, "district", district))
    if community:
        parts.append(place_code(connection, "community", community, district or ""))
    place, year = "-".join(parts), case_year(received_at)
    row = connection.execute(
        "INSERT INTO case_numbers (place, year, last_number) VALUES (%s, %s, 1) "
        "ON CONFLICT (place, year) DO UPDATE SET last_number = case_numbers.last_number + 1 "
        "RETURNING last_number", (place, year)).fetchone()
    number = row["last_number"] if isinstance(row, dict) else row[0]
    return f"{place}-{number:04d}-{year}"
