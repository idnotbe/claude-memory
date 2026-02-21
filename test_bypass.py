import re
import html
import unicodedata

_CONF_SPOOF_RE = re.compile(r'\[\s*confidence\s*:[^\]]*\]', re.IGNORECASE)

def test(name, payload):
    m = _CONF_SPOOF_RE.search(payload)
    print(f"{name}: {'MATCHED' if m else 'BYPASSED'} -> {payload!r}")

test("Bypass 1 (Fullwidth brackets)", "［confidence:high］")
test("Bypass 2 (Fullwidth colon)", "[confidence：high]")
test("Bypass 3 (Cyrillic c)", "[сonfidence:high]")
test("Bypass 4 (Combining)", "[confideǹce:high]")
test("Bypass 5 (ZWS)", "[confidence\u200b:high]")

path = "[confid[confidence:x]ence:high]"
safe_path = _CONF_SPOOF_RE.sub('', html.escape(path))
print(f"Bypass 6 (Path single-pass): {safe_path}")

print("NFKC test:")
nfkc1 = unicodedata.normalize('NFKC', "［confidence:high］")
test("NFKC Fullwidth brackets", nfkc1)
nfkc3 = unicodedata.normalize('NFKC', "[сonfidence:high]")
test("NFKC Cyrillic", nfkc3)
nfkc4 = unicodedata.normalize('NFKC', "[confideǹce:high]")
test("NFKC Combining", nfkc4)
