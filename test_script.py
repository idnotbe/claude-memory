import re
import html

_CONF_SPOOF_RE = re.compile(r'\[\s*confidence\s*:[^\]]*\]', re.IGNORECASE)

path = "foo/[con[confidence:x]fidence:high]"
safe_path = _CONF_SPOOF_RE.sub('', html.escape(path))
print(f"Path after single-pass: {safe_path}")
