import re

sanitized = "[confidence\u200b:high]"
prev_tag = None
while prev_tag != sanitized:
    prev_tag = sanitized
    sanitized = re.sub(r'\[\s*confidence\s*:[^\]]*\]', '', sanitized, flags=re.IGNORECASE)

print(f"Sanitized tag: {repr(sanitized)}")
