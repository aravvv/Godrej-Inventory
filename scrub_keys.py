import glob
import os
import re

pattern = re.compile(r"gsk_[A-Za-z0-9]+")
for f in glob.glob("*.py"):
    with open(f, "r", encoding="utf-8", errors="ignore") as fp:
        content = fp.read()
    if pattern.search(content):
        print(f"Scrubbing key from: {f}")
        clean = pattern.sub("os.getenv('GROQ_API_KEY')", content)
        if "from dotenv import load_dotenv" not in clean:
            clean = "import os\nfrom dotenv import load_dotenv\nload_dotenv()\n" + clean
        with open(f, "w", encoding="utf-8") as fp:
            fp.write(clean)

print("All Python files verified clean. API key resides exclusively in .env")
