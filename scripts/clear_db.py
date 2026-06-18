"""Utility script — wipe all claim data from the database.

Usage:
    python -m scripts.clear_db               # dry-run: shows counts, does nothing
    python -m scripts.clear_db --confirm     # actually deletes

Run from the project root (Plum - ClaimPilot/).
"""
import argparse
import asyncio
import sys

from sqlalchemy import func, select, delete

from backend.src.models.database import AsyncSessionLocal
from backend.src.models.claim import Claim, ClaimDocument


async def main() -> None:
    parser = argparse.ArgumentParser(description="Clear all claims from the database.")
    parser.add_argument("--confirm", action="store_true",
                        help="Actually delete rows (omit for dry-run)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        try:
            claim_count = (await db.execute(select(func.count()).select_from(Claim))).scalar()
            doc_count = (await db.execute(select(func.count()).select_from(ClaimDocument))).scalar()
            print(f"Found: {claim_count} claim(s), {doc_count} document(s)")

            if not args.confirm:
                print("Dry-run — nothing deleted. Pass --confirm to delete.")
                return

            await db.execute(delete(ClaimDocument))
            await db.execute(delete(Claim))
            await db.commit()
            print(f"Deleted {claim_count} claim(s) and {doc_count} document(s).")

        except Exception as e:
            await db.rollback()
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
