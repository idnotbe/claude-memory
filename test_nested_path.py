import re
import html

_CONF_SPOOF_RE = re.compile(r'\[\s*confidence\s*:[^\]]*\]', re.IGNORECASE)
path = "[confid[confidence:x]ence:high]"
safe_path = _CONF_SPOOF_RE.sub('', html.escape(path))
print("Safe Path:", safe_path)
