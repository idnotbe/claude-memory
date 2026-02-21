import sqlite3

def test_fts5():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(title, body);")
    conn.execute("INSERT INTO docs (title, body) VALUES ('Safe Doc', 'This is a normal document with no special words.');")
    conn.execute("INSERT INTO docs (title, body) VALUES ('Malicious', 'This document contains NOT and OR.');")
    conn.execute("INSERT INTO docs (title, body) VALUES ('Another', 'Has the word malicious in it.');")
    
    # Test 1: MATCH ? with raw FTS5 syntax (demonstrates MATCH ? allows FTS5 injection)
    try:
        cur = conn.execute("SELECT title FROM docs WHERE docs MATCH ?", ("title:Malicious",))
        print("Test 1 (Raw FTS5 query 'title:Malicious'):", cur.fetchall())
    except Exception as e:
        print("Test 1 Error:", e)

    # Test 2: Sanitized and quoted (alphanumeric + _.-)
    # User input "NOT malicious" -> sanitized to "NOT malicious" (if space is allowed, or tokenized to "NOT" "malicious")
    # Let's say we tokenize and quote: '"NOT" "malicious"'
    try:
        cur = conn.execute("SELECT title FROM docs WHERE docs MATCH ?", ('"NOT" "malicious"',))
        print("Test 2 (Quoted '\"NOT\" \"malicious\"'):", cur.fetchall())
    except Exception as e:
        print("Test 2 Error:", e)
        
    # Test 3: Can you escape quotes if you only have alphanumeric + _.- ?
    # If input is 'malicious" OR body:"malicious', sanitization removes quotes and colons.
    # Becomes 'malicious OR bodymalicious'. Quoted: '"malicious" "OR" "bodymalicious"'
    try:
        cur = conn.execute("SELECT title FROM docs WHERE docs MATCH ?", ('"malicious" "OR" "bodymalicious"',))
        print("Test 3 (Sanitized attack):", cur.fetchall())
    except Exception as e:
        print("Test 3 Error:", e)

test_fts5()
