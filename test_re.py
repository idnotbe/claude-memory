import re
print("Spaced match:", bool(re.search(r'\[\s*confidence\s*:[^\]]*\]', '[c o n f i d e n c e : high]', re.IGNORECASE)))
print("Kelvin sign match:", bool(re.search(r'confidence', 'confidenc\u212a', re.IGNORECASE)))
