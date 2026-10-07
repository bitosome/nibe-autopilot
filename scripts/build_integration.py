"""Package only integration runtime files, never household configs or audit data."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "nibe_autopilot"
OUTPUT = ROOT / "dist" / "nibe-autopilot.zip"
OUTPUT.parent.mkdir(exist_ok=True)
with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".png", ".svg"):
            archive.write(path, path.relative_to(ROOT))
print(OUTPUT)
