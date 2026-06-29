import re

data = open('Search _ LinkedIn_1.mhtml', 'rb').read()
raw = data.decode('utf-8', errors='replace')

# Unwrap quoted-printable and MIME folding
raw2 = re.sub(r'=\r?\n', '', raw)
raw2 = re.sub(r'\r?\n[ \t]', ' ', raw2)

print(f"Raw MHTML size: {len(raw2):,} chars")

# All linkedin post-type URLs
LI_POST = re.compile(r'https?://(?:www\.)?linkedin\.com/(?:posts|feed/update)/[^\s"\'<>\\]{5,}')
post_links = list(dict.fromkeys(m.group(0).rstrip('/= ') for m in LI_POST.finditer(raw2)))
print(f"\nPost links found: {len(post_links)}")
for l in post_links:
    print(f"  {l}")

# Broader: all linkedin URLs
LI_ALL = re.compile(r'https?://(?:www\.)?linkedin\.com/[^\s"\'<>\\]{5,}')
all_li = list(dict.fromkeys(m.group(0)[:120] for m in LI_ALL.finditer(raw2)))
print(f"\nAll LinkedIn URLs (first 30 of {len(all_li)}):")
for l in all_li[:30]:
    print(f"  {l}")

# Check for URNs
urns = re.findall(r'urn:li:(?:activity|share|ugcPost):\d+', raw2)
print(f"\nURNs found: {len(urns)}")
for u in list(dict.fromkeys(urns))[:20]:
    print(f"  {u}")
