"""Utility script — wipe all claim data from the database.

Usage:
    python -m scripts.clear_db               # dry-run: shows counts, does nothing
    python -m scripts.clear_db --confirm     # actually deletes

Run from the project root (Plum - ClaimPilot/).
"""
import argparse
import sys

from backend.src.models.database import SessionLocal
from backend.src.models.claim import Claim, ClaimDocument


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear all claims from the database.")
    parser.add_argument("--confirm", action="store_true",
                        help="Actually delete rows (omit for dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        doc_count = db.query(ClaimDocument).count()
        claim_count = db.query(Claim).count()
        print(f"Found: {claim_count} claim(s), {doc_count} document(s)")

        if not args.confirm:
            print("Dry-run — nothing deleted. Pass --confirm to delete.")
            return

        db.query(ClaimDocument).delete()
        db.query(Claim).delete()
        db.commit()
        print(f"Deleted {claim_count} claim(s) and {doc_count} document(s).")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
