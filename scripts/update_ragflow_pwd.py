"""Update RAGFlow admin password via MySQL."""
import pymysql

new_hash = "scrypt:32768:8:1$xN4H9x9WLVwZ8Ue/YarQUw==$8a3790d29277396862ad3fdfb8ccdd54eeed10d88ec708aedd96a3996262c8ca374f4df19655991c726ac0b3b3d8698c92eb42054daa68d6dc932851fb565f3f"

conn = pymysql.connect(
    host='localhost', port=3307,
    user='root', password='infini_rag_flow',
    database='rag_flow'
)
cur = conn.cursor()
cur.execute("UPDATE user SET password=%s WHERE email=%s", (new_hash, 'admin@ragflow.io'))
conn.commit()
print(f"Updated {cur.rowcount} row(s)")
cur.close()
conn.close()
