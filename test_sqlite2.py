import sqlite3
conn = sqlite3.connect(":memory:")
conn.execute("CREATE VIRTUAL TABLE t USING fts5(text)")
conn.execute("INSERT INTO t VALUES ('file.txt')")

try:
    res = conn.execute("SELECT text FROM t WHERE t MATCH 'file.txt'").fetchall()
    print("Without quotes 'file.txt':", res)
except Exception as e:
    print("Error without quotes:", e)
