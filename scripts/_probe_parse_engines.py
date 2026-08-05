from app.db.session import SessionLocal
from app.models.document import Document

names = [
    "003_由你人資MOU.pdf",
    "023_KiGo使用手冊.pdf",
    "006_ETI-Base-Code-Burmese.pdf",
    "002_11410_83028948_營業稅繳款書(401)_.pdf",
    "005_11408_83028948_營業稅繳款書(401)_.pdf",
    "010_補印發票切結書.pdf",
]
db = SessionLocal()
rows = (
    db.query(Document)
    .filter(Document.filename.in_(names), Document.tombstoned_at.is_(None))
    .all()
)
for d in rows:
    qr = d.quality_report if isinstance(d.quality_report, dict) else {}
    print(
        f"{d.filename[:42]:42} status={d.status:10} "
        f"engine={qr.get('parse_engine')} ocr={qr.get('ocr_used')} "
        f"route={qr.get('parse_route')} cloud={bool(qr.get('cloud_ocr'))}"
    )
db.close()
