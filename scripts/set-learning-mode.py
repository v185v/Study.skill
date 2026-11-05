#!/usr/bin/env python3
"""Switch chapter access without modifying teaching mode or either progress record."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "viewer"))
from learning_modes import set_learning_mode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("course_state_dir", type=Path)
    parser.add_argument("mode", choices=["guided", "free"])
    args = parser.parse_args()
    meta = set_learning_mode(args.course_state_dir, args.mode)
    print(json.dumps({"learning_mode": meta.get("learning_mode", "guided"), "mode": meta.get("mode")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
