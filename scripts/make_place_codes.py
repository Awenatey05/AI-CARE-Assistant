"""
MAKE PLACE CODES (case references, e.g. NR-TML-GUM-0012-2026)

Builds a first draft of data/place_codes.json from the places in the data, using
the rules in app/services/case_ref.py. All 16 regions are listed (the Kobo form
offers all of them). Communities are grouped under their district, because a
community code only has to be unique within its district.
The file is meant to be corrected by hand; run this script again only to start over.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from app.services.case_ref import community_code, district_code

DATA = Path("data")
REGIONS = {"ahafo": "AH", "ashanti": "AS", "bono": "BO", "bono_east": "BE", "central": "CR",
           "eastern": "ER", "greater_accra": "GA", "north_east": "NE", "northern": "NR", "oti": "OT",
           "savannah": "SV", "upper_east": "UE", "upper_west": "UW", "volta": "VR", "western": "WR",
           "western_north": "WN"}


if __name__ == "__main__":
    field = json.loads((DATA / "field_submissions.json").read_text()) + json.loads((DATA / "edge_cases.json").read_text())
    calls = json.loads((DATA / "helpline_reports.json").read_text())
    uploads = json.loads((DATA / "uploads" / "uploads_manifest.json").read_text())

    districts = {s.get("interview/district") for s in field} | {c.get("district") for c in calls} | {u["district"] for u in uploads}
    communities: dict[str, dict[str, str]] = defaultdict(dict)
    for s in field:
        if s.get("interview/community"):
            communities[s["interview/district"]][s["interview/community"]] = community_code(s["interview/community"])

    codes = {
        "regions": REGIONS,
        "districts": {d: district_code(d) for d in sorted(d for d in districts if d)},
        "communities": {d: dict(sorted(places.items())) for d, places in sorted(communities.items())},
    }

    # Two districts must never share a code; two communities only within the same district.
    for code, n in Counter(codes["districts"].values()).items():
        if n > 1:
            print(f"Same district code {code}: correct by hand")
    for district, places in codes["communities"].items():
        for code, n in Counter(places.values()).items():
            if n > 1:
                print(f"Same community code {code} in {district}: correct by hand")

    (DATA / "place_codes.json").write_text(json.dumps(codes, indent=1, ensure_ascii=False) + "\n")
    print(f"Saved data/place_codes.json: {len(REGIONS)} regions, {len(codes['districts'])} districts, "
          f"{sum(len(p) for p in codes['communities'].values())} communities")
