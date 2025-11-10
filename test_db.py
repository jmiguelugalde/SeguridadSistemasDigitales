import os, pymysql
print("INTENTANDO:", os.getenv("DB_HOST"), os.getenv("DB_PORT"), os.getenv("DB_USER"), os.getenv("DB_NAME"))
conn = pymysql.connect(
    host="localhost",
    port=3306,
    user="etl_user",
    password="admin123",
    database="dw",
    connect_timeout=5,
)
with conn.cursor() as cur:
    cur.execute("SELECT VERSION();")
    print("OK:", cur.fetchone()[0])
conn.close()
