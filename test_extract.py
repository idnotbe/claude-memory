from hooks.scripts.memory_retrieve import extract_body_text, BODY_FIELDS

data = {
    "category": "DECISION",
    "content": {
        "context": "We needed a database.",
        "decision": "Use PostgreSQL."
    }
}
print("UPPERCASE CATEGORY:", repr(extract_body_text(data)))

data2 = {
    "category": "decision",
    "content": {
        "context": "We needed a database.",
        "decision": "Use PostgreSQL."
    }
}
print("LOWERCASE CATEGORY:", repr(extract_body_text(data2)))
