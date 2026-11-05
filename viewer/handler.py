"""HTTP routes for the local study.skill viewer."""

import json
import subprocess
import sys
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from course_state import build_initial_state, discover_courses
from learning_modes import learning_mode, learning_record_path, set_learning_mode
from diagrams import render_diagram_svg
from records import load_learning_record, merge_learning_record_event, now_iso, write_learning_record
from utils import content_type_for, safe_resolve, validate_slug, load_json


class LearningModeChanged(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ViewerContext:
    session_token: str
    learning_root: Path
    course_slug: str | None
    profile_dir: Path
    viewer_html_path: Path
    viewer_asset_dir: Path
    script_dir: Path
    server_mode: str


class ViewerHandler(SimpleHTTPRequestHandler):
    context: ClassVar[ViewerContext]

    def log_message(self, format, *args):
        pass

    def _check_token(self, query=None, headers=True):
        if query:
            token = query.get("token", [None])[0]
            if token == self.context.session_token:
                return True
        if headers:
            token = self.headers.get("X-Session-Token")
            if token == self.context.session_token:
                return True
        return False

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _selected_course(self, query=None) -> str:
        slug = (query or {}).get("course", [None])[0] or self.headers.get("X-Course-Slug") or self.context.course_slug
        if not slug or not validate_slug(slug) or slug in {".", ".."}:
            raise ValueError("select a valid course first")
        if not (self.context.learning_root / "courses" / slug).is_dir():
            raise ValueError("course directory not found")
        return slug

    def _course_record(self, body) -> tuple[str, Path]:
        slug = self._selected_course()
        directory = self.context.profile_dir / "courses" / slug
        meta = load_json(directory / "meta.json")
        if meta.get("generation_status") != "complete":
            raise PermissionError("course generation is not complete")
        mode = learning_mode(meta)
        requested_mode = body.get("learning_mode", self.headers.get("X-Learning-Mode", "guided"))
        if requested_mode != mode:
            raise LearningModeChanged("学习模式已变化，请刷新页面后继续。")
        return slug, learning_record_path(directory, mode)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)

        if path == "/":
            self._serve_viewer()
        elif path in {"/api/initial-state", "/api/courses"}:
            if not self._check_token(query):
                self.send_error(401, "invalid token")
                return
            if path == "/api/courses":
                self._send_json({"courses": discover_courses(self.context.learning_root), "server_mode": self.context.server_mode})
            else:
                self._serve_initial_state(query)
        elif path.startswith("/assets/"):
            self._serve_static_asset(path)
        elif path.startswith("/file/"):
            self._serve_course_file(path)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._check_token():
            self.send_error(401, "invalid token")
            return

        if path == "/api/review-rating":
            self._handle_review_rating()
        elif path == "/api/learning-record":
            self._handle_learning_record()
        elif path == "/api/render-diagram":
            self._handle_render_diagram()
        elif path == "/api/learning-mode":
            self._handle_learning_mode()
        else:
            self.send_error(404)

    def _handle_review_rating(self):
        if self.context.server_mode != "interactive":
            self.send_error(403, "not available in read-only mode")
            return
        try:
            body = self._read_body()
            course_slug, record_path = self._course_record(body)
            concept_id = body.get("concept_id")
            rating = body.get("rating")
            if not concept_id or rating not in (1, 2, 3, 4):
                self._send_json({"error": "invalid params: need concept_id and rating 1-4"}, 400)
                return

            course_state_dir = str(self.context.profile_dir / "courses" / course_slug)
            command = [
                sys.executable,
                str(self.context.script_dir / "record-review.py"),
                course_state_dir,
                concept_id,
                str(rating),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                self._send_json({"error": result.stderr.strip() or "record-review.py failed"}, 500)
                return

            concept = json.loads(result.stdout.strip())
            timestamp = now_iso()
            record = load_learning_record(record_path, course_slug)
            payload = {
                "item": {
                    "concept_id": concept_id,
                    "rating": rating,
                    "next_review": concept.get("next_review", ""),
                },
            }
            record = merge_learning_record_event(record, "review_rated", payload, timestamp)
            write_learning_record(record_path, record)
            self._send_json({"ok": True, "concept": concept})
        except LearningModeChanged as exc:
            self._send_json({"error": str(exc)}, 409)
        except FileNotFoundError:
            self._send_json({"error": "bundled record-review.py not found"}, 500)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_learning_record(self):
        if self.context.server_mode != "interactive":
            self.send_error(403, "not available in read-only mode")
            return
        try:
            body = self._read_body()
            course_slug, record_path = self._course_record(body)
            if body.get("source") != "study.skill.viewer":
                self._send_json({"error": "invalid source"}, 400)
                return
            if body.get("course_slug") != course_slug:
                self._send_json({"error": "course_slug mismatch"}, 400)
                return
            payload = body.get("payload")
            if not isinstance(payload, dict):
                self._send_json({"error": "payload must be object"}, 400)
                return
            timestamp = now_iso()
            event = str(body.get("event") or "")
            record = load_learning_record(record_path, course_slug)
            try:
                record = merge_learning_record_event(record, event, payload, timestamp)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            write_learning_record(record_path, record)
            self._send_json({"ok": True, "path": str(record_path), "record": record})
        except LearningModeChanged as exc:
            self._send_json({"error": str(exc)}, 409)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_learning_mode(self):
        if self.context.server_mode != "interactive":
            self._send_json({"error": "只读模式不能切换学习方式，请以 interactive 启动。"}, 403)
            return
        try:
            body = self._read_body()
            slug, _ = self._course_record(body)
            meta = set_learning_mode(self.context.profile_dir / "courses" / slug, body.get("mode"))
            self._send_json({"ok": True, "learning_mode": learning_mode(meta)})
        except LearningModeChanged as exc:
            self._send_json({"error": str(exc)}, 409)
        except (ValueError, PermissionError) as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_render_diagram(self):
        try:
            body = self._read_body()
            diagram_type = str(body.get("type", "")).strip().lower()
            source = body.get("source")
            if not isinstance(source, str):
                self._send_json({"error": "invalid params: need supported type and source"}, 400)
                return
            svg = render_diagram_svg(diagram_type, source)
            self._send_json({"ok": True, "svg": svg})
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_viewer(self):
        try:
            content = self.context.viewer_html_path.read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        except Exception as exc:
            self.send_error(500, str(exc))

    def _serve_initial_state(self, query):
        try:
            slug = self._selected_course(query)
            module = query.get("module", [None])[0]
            section = query.get("section", [None])[0]
            state = build_initial_state(
                self.context.learning_root,
                slug,
                self.context.script_dir,
                module,
                section,
            )
            state["server_mode"] = self.context.server_mode
            self._send_json(state)
        except PermissionError as exc:
            self._send_json({"error": str(exc)}, 403)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _serve_static_asset(self, path: str):
        rel_path = path.removeprefix("/assets/")
        self._serve_local_file(self.context.viewer_asset_dir, rel_path)

    def _serve_course_file(self, path: str):
        parts = path.split("/", 3)
        if len(parts) < 4:
            self.send_error(400, "invalid path")
            return
        slug = parts[2]
        rel_path = parts[3]

        if not validate_slug(slug):
            self.send_error(400, "invalid slug")
            return

        self._serve_local_file(self.context.learning_root / "courses" / slug, rel_path)

    def _serve_local_file(self, base: Path, rel_path: str):
        try:
            target = safe_resolve(base, rel_path)
        except ValueError:
            self.send_error(403, "path traversal")
            return

        if not target.exists() or not target.is_file():
            self.send_error(404, "file not found")
            return

        try:
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type_for(target))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.send_error(500, str(exc))


def make_handler(context: ViewerContext):
    class ConfiguredViewerHandler(ViewerHandler):
        pass

    ConfiguredViewerHandler.context = context
    return ConfiguredViewerHandler
