#!/usr/bin/env python3
"""study.skill viewer server.

Usage:
  python viewer/server.py [--learning-root <path>] [--course <slug>]
                         [--learning-mode guided|free] [--mode interactive|read-only]
                         [--module <module>] [--section <section>] [--port <port>]

Without --course, opens the course library. The default learning root is ~/learning.

Modes:
  interactive - Allows review ratings and learning record writing.
                Requires bundled check-reviews.py and record-review.py.
  read-only   - Only serves course content. Does not require record-review.py.
                Does not expose /api/review-rating or /api/learning-record.
"""

import argparse
import sys
import uuid
import webbrowser
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import urlencode

from handler import ViewerContext, make_handler
from utils import validate_slug
from learning_modes import set_learning_mode


sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def validate_scripts(script_dir: Path, mode: str) -> list[str]:
    if mode != "interactive":
        return []
    required = [
        (script_dir / "check-reviews.py", "check-reviews.py"),
        (script_dir / "record-review.py", "record-review.py"),
    ]
    return [name for path, name in required if not path.is_file()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="study.skill viewer server")
    parser.add_argument("--course", help="Course slug; omit to open the course library")
    parser.add_argument("--learning-root", default=str(Path.home() / "learning"), help="Learning data root directory (default: ~/learning)")
    parser.add_argument("--mode", default="interactive", choices=["read-only", "interactive"], help="Server mode")
    parser.add_argument("--learning-mode", choices=["guided", "free"], help="Switch the selected course's learning access policy")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser")
    parser.add_argument("--module", default=None, help="Module to display initially")
    parser.add_argument("--section", default=None, help="Section to display initially")
    parser.add_argument("--port", type=int, default=0, help="Port (0 = random)")
    return parser.parse_args()


def validate_paths(learning_root: Path, course_slug: str | None, viewer_dir: Path) -> None:
    if not learning_root.exists():
        print(f"Error: learning-root does not exist: {learning_root}", file=sys.stderr)
        sys.exit(1)
    if not (learning_root / ".learning-profile").is_dir():
        print(f"Error: .learning-profile/ not found in {learning_root}", file=sys.stderr)
        sys.exit(1)
    if course_slug is not None and (not validate_slug(course_slug) or course_slug in {".", ".."}):
        print(f"Error: invalid course slug: {course_slug}", file=sys.stderr)
        sys.exit(1)
    course_dir = learning_root / "courses" / course_slug if course_slug else None
    if course_dir is not None and not course_dir.is_dir():
        print(f"Error: course directory not found: {course_dir}", file=sys.stderr)
        sys.exit(1)
    if not (viewer_dir / "viewer.html").exists():
        print(f"Error: viewer.html not found: {viewer_dir / 'viewer.html'}", file=sys.stderr)
        sys.exit(1)
    for asset_name in ("viewer.css", "viewer.js"):
        asset_path = viewer_dir / "assets" / asset_name
        if not asset_path.exists():
            print(f"Error: viewer asset not found: {asset_path}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    args = parse_args()
    viewer_dir = Path(__file__).resolve().parent
    script_dir = viewer_dir.parent / "scripts"
    learning_root = Path(args.learning_root).expanduser().resolve()
    course_slug = args.course
    profile_dir = learning_root / ".learning-profile"
    validate_paths(learning_root, course_slug, viewer_dir)
    if args.learning_mode and (not course_slug or args.mode == "read-only"):
        sys.exit("--learning-mode requires --course and --mode interactive")
    if (args.module or args.section) and not course_slug:
        sys.exit("--module/--section require --course")
    if args.learning_mode:
        set_learning_mode(profile_dir / "courses" / course_slug, args.learning_mode)
    missing = validate_scripts(script_dir, args.mode)
    if missing:
        print(f"Error: missing required scripts for {args.mode} mode: {', '.join(missing)}", file=sys.stderr)
        print(f"  Expected in: {script_dir}", file=sys.stderr)
        print("  Reinstall or repair the study skill files before using interactive mode.", file=sys.stderr)
        sys.exit(1)

    session_token = str(uuid.uuid4())
    context = ViewerContext(
        session_token=session_token,
        learning_root=learning_root,
        course_slug=course_slug,
        profile_dir=profile_dir,
        viewer_html_path=viewer_dir / "viewer.html",
        viewer_asset_dir=viewer_dir / "assets",
        script_dir=script_dir,
        server_mode=args.mode,
    )
    server = HTTPServer(("127.0.0.1", args.port), make_handler(context))
    port = server.server_address[1]
    query_args = {"course": course_slug} if course_slug else {}
    if args.module:
        query_args["module"] = args.module
    if args.section is not None:
        query_args["section"] = args.section
    query = "?" + urlencode(query_args) if query_args else ""
    url = f"http://127.0.0.1:{port}/{query}#token={session_token}"

    print("study.skill viewer started", flush=True)
    print(f"  mode: {args.mode}", flush=True)
    print(f"  course: {course_slug or 'course library'}", flush=True)
    print(f"  learning-root: {learning_root}", flush=True)
    print(f"  url: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("viewer stopped")


if __name__ == "__main__":
    main()
