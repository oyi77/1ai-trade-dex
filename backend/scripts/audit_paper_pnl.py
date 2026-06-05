from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.core.paper_pnl_audit import audit_paper_pnl, apply_paper_pnl_recalculation
from backend.models.database import SessionLocal


def _sqlite_db_path() -> Path | None:
    database_url = settings.DATABASE_URL
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = database_url.replace("sqlite:///", "", 1)
    return Path(raw_path).resolve()


def _backup_sqlite_database(backup_path: str | None = None) -> str | None:
    db_path = _sqlite_db_path()
    if db_path is None or not db_path.exists():
        return None
    if backup_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = db_path.with_suffix(db_path.suffix + f".{stamp}.bak")
    else:
        backup = Path(backup_path).resolve()
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, backup)
    return str(backup)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run audit of historical paper PnL")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-apply", action="store_true")
    parser.add_argument("--backup-path", default=None)
    parser.add_argument("--external-backup-confirmed", action="store_true")
    args = parser.parse_args()

    if args.apply and not args.confirm_apply:
        print("REFUSING APPLY — pass --confirm-apply after taking/accepting a backup.")
        return 2
    if args.apply and _sqlite_db_path() is None and not args.external_backup_confirmed:
        print(
            "REFUSING APPLY — non-SQLite database detected; create a database backup "
            "and pass --external-backup-confirmed."
        )
        return 2

    db = SessionLocal()
    try:
        if args.apply:
            backup = _backup_sqlite_database(args.backup_path)
            result = apply_paper_pnl_recalculation(
                db, limit=args.limit, top_n=args.top_n
            )
            db.commit()
            print(json.dumps(dataclasses.asdict(result), indent=2, sort_keys=True))
            if backup:
                print(f"SQLite backup written: {backup}")
            elif _sqlite_db_path() is None:
                print("External backup confirmation accepted for non-SQLite database.")
            if result.updated_trade_count:
                print(
                    "APPLY COMPLETE — mismatched paper Trade.pnl rows and BotState paper cache updated."
                )
            else:
                print("APPLY COMPLETE — no paper Trade.pnl mismatches required updates.")
        else:
            report = audit_paper_pnl(db, limit=args.limit, top_n=args.top_n)
            print(json.dumps(dataclasses.asdict(report), indent=2, sort_keys=True))
            print("DRY RUN — no Trade or BotState rows were mutated.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(_main())
