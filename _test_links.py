from src.collectors import from_html
from src.extractor import extract

# Simulate HTML with relative hrefs (common in HTML-only saves)
HTML = """
<html><body>
<div class="_54096e47 edb9dae4">
  <a href="/posts/anisha-vaz_datascientist-hiring-activity-7472629903130177536-xyz/">Anisha post</a>
  <p>We are Hiring | Data Scientist | Mumbai | 3-7 years<br>
  Send CV to anisha@novotreeminds.com</p>
</div>
<div class="_54096e47 edb9dae4">
  Feed post
  <a href="/feed/update/urn:li:share:789012345678/">Share link</a>
  <p>Senior Engineer role at TechCorp Pune 5+ years. Email: hr@techcorp.com</p>
</div>
</body></html>
"""

items = list(from_html(HTML))
print(f"Items: {len(items)}")
for i, item in enumerate(items):
    p = extract(item, [])
    print(f"\n[{i+1}] post_link = {p.post_link!r}")
    print(f"     hr_mail  = {p.hr_mail!r}")
    print(f"     role     = {p.role!r}")
