"""部署後驗證：模組/任務定義數量與清單。"""
from app.db.session import SessionLocal
from app.models.mka import JobModule, TaskDefinition


def main() -> None:
    db = SessionLocal()
    try:
        mods = db.query(JobModule).all()
        tasks = db.query(TaskDefinition).all()
        print(f"modules={len(mods)}")
        print(f"module_keys={sorted(m.module_key for m in mods)}")
        print(f"tasks={len(tasks)}")
        print(f"task_keys={sorted(t.task_key for t in tasks)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
