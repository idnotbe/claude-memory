import sqlite3
conn = sqlite3.connect(":memory:")
conn.execute("CREATE VIRTUAL TABLE t USING fts5(text)")
conn.execute("INSERT INTO t VALUES ('my-variable is here')")
conn.execute("INSERT INTO t VALUES ('my variable is here')")
conn.execute("INSERT INTO t VALUES ('my only is here')")

# Query with my-variable (without quotes)
try:
    res = conn.execute("SELECT text FROM t WHERE t MATCH 'my-variable'").fetchall()
    print("Without quotes 'my-variable':", res)
except Exception as e:
    print("Error without quotes:", e)

# Query with quotes '"my-variable"'
try:
    res = conn.execute("SELECT text FROM t WHERE t MATCH '\"my-variable\"'").fetchall()
    print("With quotes '\"my-variable\"':", res)
except Exception as e:
    print("Error with quotes:", e)
