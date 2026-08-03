import json
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service.main import app

spec = app.openapi()
with open("openapi.json", "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("openapi.json generated")
print("paths:", list(spec["paths"].keys()))
