candidates = [{"tags": ["a", ["b"]]}, {"tags": 123}, {"tags": "string"}, {"tags": None}]

for c in candidates:
    raw_tags = c.get("tags", [])
    if not isinstance(raw_tags, (list, set, tuple)):
        raw_tags = [raw_tags] if raw_tags else []
    tags = ", ".join(sorted(str(t) for t in raw_tags))
    print(tags)
