import sqlite3
import time
import random
import string

def check_fts5():
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False

def generate_text(length):
    return ''.join(random.choices(string.ascii_lowercase + ' ', k=length))

def run_benchmark(num_docs, body_size):
    print(f"\n--- Benchmarking {num_docs} documents (Body size: {body_size} chars) ---")
    
    docs = []
    for i in range(num_docs):
        title = f"Title {i} " + generate_text(20)
        tags = "tag1 tag2 " + generate_text(10)
        body = generate_text(body_size) if body_size > 0 else ""
        docs.append((title, tags, body))
        
    start_total = time.perf_counter()
    
    conn = sqlite3.connect(':memory:')
    
    # 1. Schema creation
    start = time.perf_counter()
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(title, tags, body)")
    schema_time = time.perf_counter() - start
    
    # 2. Insertion
    start = time.perf_counter()
    conn.executemany("INSERT INTO docs (title, tags, body) VALUES (?, ?, ?)", docs)
    conn.commit()
    insert_time = time.perf_counter() - start
    
    # 3. Querying (BM25)
    start = time.perf_counter()
    cursor = conn.execute("SELECT title, rank FROM docs WHERE docs MATCH 'title OR tag1' ORDER BY rank LIMIT 10")
    results = cursor.fetchall()
    query_time = time.perf_counter() - start
    
    total_time = time.perf_counter() - start_total
    
    print(f"Schema Setup:  {schema_time*1000:.2f} ms")
    print(f"Insertion:     {insert_time*1000:.2f} ms")
    print(f"Query (BM25):  {query_time*1000:.2f} ms")
    print(f"Total Time:    {total_time*1000:.2f} ms")

if not check_fts5():
    print("FTS5 is not available in this Python SQLite build.")
else:
    print("FTS5 is available. Running benchmarks...")
    run_benchmark(500, 0)      # Title + Tags only
    run_benchmark(500, 2000)   # Title + Tags + 2000 char body
    run_benchmark(1000, 2000)  # 1000 docs, full body
    run_benchmark(5000, 2000)  # 5000 docs, full body

