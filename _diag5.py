import re, email as _email
from bs4 import BeautifulSoup

data = open('Search _ LinkedIn_1.mhtml', 'rb').read()
msg = _email.message_from_bytes(data)
html = ""
for part in msg.walk():
    if part.get_content_type() == "text/html" and not html:
        payload = part.get_payload(decode=True)
        if payload:
            charset = part.get_content_charset() or "utf-8"
            html = payload.decode(charset, errors="replace")

soup = BeautifulSoup(html, "html.parser")

# Find containers that have /in/ links directly inside them (not recursive)
count = 0
for tag in soup.find_all(True, limit=10000):
    if not hasattr(tag, 'find_all'):
        continue
    children_a = [a for a in tag.find_all('a', recursive=False) if '/in/' in (a.get('href',''))]
    if children_a:
        hrefs = [a.get('href','') for a in children_a]
        text = tag.get_text()[:80]
        print(f"<{tag.name} class={str(tag.get('class',''))[:50]}>")
        print(f"  hrefs={hrefs[:3]}")
        print(f"  text: {text!r}")
        count += 1
        if count >= 12:
            break
