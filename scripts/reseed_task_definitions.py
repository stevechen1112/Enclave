"""Reapply canonical task definitions after a task contract deployment."""
from app.db.session import SessionLocal
from app.services.mka_module_seed import seed_canonical_task_definitions


def main() -> int:
    db = SessionLocal()
    try:
        count = seed_canonical_task_definitions(db)
        db.commit()
        print(f"seeded task definitions: {count}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
