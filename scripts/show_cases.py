"""
SHOW CASES: what is saved in Postgres.

For each case: the ID it arrived with, the readable reference it was given,
its channel and outcome; then the alerts and the numbers used per place.
Prints no names or report text.

Run from the project folder:
    python -m scripts.show_cases
    python -m scripts.show_cases --limit 50
"""

from __future__ import annotations

import argparse

from app.core.db import connect

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show the cases saved in Postgres")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    with connect() as connection:
        total = connection.execute("SELECT count(*) FROM cases").fetchone()["count"]
        print(f"CASES IN POSTGRES ({total}; showing the latest {args.limit}):")
        for row in connection.execute(
                "SELECT id, case_ref, channel, status, band, alert FROM cases "
                "ORDER BY created_at DESC LIMIT %s", (args.limit,)):
            print(f"  arrived as {row['id'][:36]:36} -> {row['case_ref'] or '(no reference)':24} "
                  f"{row['channel']:8} {row['band'] or row['status']:22} alert={row['alert']}")

        print("\nOPEN ALERTS:")
        for row in connection.execute(
                "SELECT a.id, c.case_ref, a.reasons, a.escalation_level FROM alerts a "
                "JOIN cases c ON c.id = a.case_id WHERE a.status = 'open' ORDER BY a.created_at"):
            print(f"  alert {row['id']:4} {row['case_ref']:24} {', '.join(row['reasons'])} "
                  f"(escalation level {row['escalation_level']})")

        print("\nNUMBERS USED PER PLACE AND YEAR:")
        for row in connection.execute("SELECT place, year, last_number FROM case_numbers ORDER BY place, year"):
            print(f"  {row['place']:16} {row['year']}: {row['last_number']}")

        unchecked = connection.execute("SELECT kind, name, district, code FROM place_codes WHERE NOT checked").fetchall()
        print(f"\nNEW PLACE CODES NOT YET CHECKED: {len(unchecked)}")
        for row in unchecked:
            print(f"  {row['kind']:9} {row['name']} ({row['district'] or '-'}) -> {row['code']}")
