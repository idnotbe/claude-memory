import re
import unicodedata

def _sanitize_title(title: str) -> str:
    # Strip control characters
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    # Strip zero-width, bidirectional override, and tag Unicode characters
    title = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]', '', title)
    return title

print("ZWS in title:", repr(_sanitize_title("[confidence\u200b:high]")))
