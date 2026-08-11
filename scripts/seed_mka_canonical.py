"""部署後一次性 seed：canonical 模組 + 任務定義（冪等）。"""
from app.db.session import SessionLocal
from app.services.mka_module_seed import (
    seed_canonical_modules,
    seed_canonical_task_definitions,
)


def main() -> None:
    db = SessionLocal()
    try:
        m = seed_canonical_modules(db)
        t = seed_canonical_task_definitions(db)
        db.commit()
        print(f"modules_seeded={m}")
        print(f"tasks_seeded={t}")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"SEED_ERROR: {type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
