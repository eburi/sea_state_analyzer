"""Project-root entry point – delegates to src/main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from main import main  # noqa: E402

if __name__ == "__main__":
    main()
