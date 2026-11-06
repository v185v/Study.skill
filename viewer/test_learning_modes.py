"""Behavior checks for independent learning, access rules, and progress preservation."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from course_state import build_initial_state
from handler import ViewerContext, make_handler
from learning_modes import set_learning_mode
from records import default_learning_record


VIEWER_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = VIEWER_DIR.parent / "scripts"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class LearningModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="study modes ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "我的课程"
        self.profile = self.root / ".learning-profile"
        write_json(self.profile / "profile.json", {"schema_version": 5})
        self.directory = self.create_course("algorithms")
        self.server = None

    def create_course(self, slug):
        directory = self.profile / "courses" / slug
        write_json(directory / "meta.json", {
            "schema_version": 5, "slug": slug, "name": "数据结构与算法",
            "generation_status": "complete", "status": "active",
            "mode": "system", "mode_label": "系统精讲",
            "current_module": "01-arrays", "completed_modules": [],
            "total_sessions": 3, "streak_days": 2,
        })
        write_json(directory / "params.json", {"require_mastery_before_advance": True})
        write_json(directory / "concepts.json", {"concepts": []})
        write_json(directory / "domain-tree.json", {
            "nodes": {"01-arrays": {"status": "in_progress", "progress": 40},
                      "02-graphs": {"status": "locked", "prerequisites": ["01-arrays"]}},
            "rpg": {"xp": 75, "level": 1},
        })
        record = default_learning_record(slug, "2026-11-06T01:00:00Z")
        record["current"] = {"module": "01-arrays", "section": "01-intro"}
        record["questions_for_llm"] = ["原模式的问题"]
        write_json(directory / "learning-record.json", record)
        for module in ("01-arrays", "02-graphs"):
            page = self.root / "courses" / slug / module / "01-intro" / "content.md"
            page.parent.mkdir(parents=True)
            page.write_text(f"# {module}\n\n课程正文", encoding="utf-8")
            (page.parent.parent / "content.md").write_text(f"# {module}", encoding="utf-8")
        return directory

    def start_server(self, mode="interactive", course=None):
        context = ViewerContext(
            session_token="test-token", learning_root=self.root, course_slug=course,
            profile_dir=self.profile, viewer_html_path=VIEWER_DIR / "viewer.html",
            viewer_asset_dir=VIEWER_DIR / "assets", script_dir=SCRIPT_DIR,
            server_mode=mode,
        )
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(context))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, body=None, mode="guided", course="algorithms"):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, headers={
            "X-Session-Token": "test-token", "Content-Type": "application/json",
            "X-Course-Slug": course, "X-Learning-Mode": mode,
        })
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_round_trip_keeps_original_progress_and_independent_free_cursor(self):
        self.start_server()
        protected = {name: (self.directory / name).read_bytes() for name in (
            "learning-record.json", "params.json", "domain-tree.json", "concepts.json"
        )}
        original_meta = json.loads((self.directory / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(self.request("/api/initial-state?module=02-graphs")[0], 403)
        self.assertEqual(self.request("/api/learning-mode", {"mode": "free"})[0], 200)
        status, state = self.request("/api/initial-state?module=02-graphs&section=01-intro", mode="free")
        self.assertEqual(status, 200)
        self.assertEqual(state["current_module"], "02-graphs")
        self.assertEqual(state["learning_record_file"], "free-learning-record.json")
        self.assertEqual(state["learning_record"]["questions_for_llm"], [])
        payload = {"module": "02-graphs", "section": "01-intro",
                   "content_file": "algorithms/02-graphs/01-intro/content.md", "started_at": "2026-11-06T02:00:00Z"}
        for event, event_payload in (
            ("page_view", payload),
            ("question_added", {"question": "图怎么遍历？"}),
            ("exercise_submitted", {"exercise": {"id": "graph-1", "module": "02-graphs", "section": "01-intro", "user_answer": "BFS"}}),
            ("completion", payload),
        ):
            self.assertEqual(self.request("/api/learning-record", {
                "source": "study.skill.viewer", "course_slug": "algorithms", "learning_mode": "free",
                "event": event, "payload": event_payload,
            }, mode="free")[0], 200)
        self.assertEqual(self.request("/api/learning-mode", {"mode": "guided"}, mode="free")[0], 200)
        _, guided = self.request("/api/initial-state")
        self.assertEqual((guided["current_module"], guided["current_section"]), ("01-arrays", "01-intro"))
        self.assertEqual(guided["learning_record"]["questions_for_llm"], ["原模式的问题"])
        self.assertEqual(self.request("/api/initial-state?module=02-graphs")[0], 403)
        for name, original in protected.items():
            self.assertEqual((self.directory / name).read_bytes(), original, name)
        meta = json.loads((self.directory / "meta.json").read_text(encoding="utf-8"))
        meta.pop("learning_mode")
        self.assertEqual(meta, original_meta)
        self.request("/api/learning-mode", {"mode": "free"})
        _, free = self.request("/api/initial-state", mode="free")
        self.assertEqual((free["current_module"], free["current_section"]), ("02-graphs", "01-intro"))
        self.assertEqual(free["learning_record"]["exercises"][0]["user_answer"], "BFS")

    def test_stale_tab_cannot_write_to_other_mode(self):
        self.start_server()
        self.request("/api/learning-mode", {"mode": "free"})
        status, _ = self.request("/api/learning-record", {
            "source": "study.skill.viewer", "course_slug": "algorithms",
            "event": "question_added", "payload": {"question": "stale"},
        })
        self.assertEqual(status, 409)
        self.assertFalse((self.directory / "free-learning-record.json").exists())

    def test_library_and_multiple_courses(self):
        second = self.create_course("another-course")
        meta = json.loads((second / "meta.json").read_text(encoding="utf-8"))
        meta["generation_status"] = "pending_review"
        write_json(second / "meta.json", meta)
        self.start_server()
        _, library = self.request("/api/courses", course="")
        self.assertEqual(len(library["courses"]), 2)
        self.assertEqual([c["ready"] for c in library["courses"]], [True, False])
        self.assertEqual(self.request("/api/initial-state", course="another-course")[0], 403)
        meta["generation_status"] = "complete"
        write_json(second / "meta.json", meta)
        self.assertEqual(self.request("/api/learning-mode", {"mode": "free"}, course="another-course")[0], 200)
        status, state = self.request("/api/initial-state?module=02-graphs", mode="free", course="another-course")
        self.assertEqual(status, 200)
        self.assertEqual(state["course_slug"], "another-course")
        self.assertNotIn("learning_mode", json.loads((self.directory / "meta.json").read_text(encoding="utf-8")))

    def test_read_only_obeys_access_and_never_writes(self):
        self.start_server(mode="read-only")
        self.assertEqual(self.request("/api/initial-state?module=02-graphs")[0], 403)
        self.assertEqual(self.request("/api/learning-mode", {"mode": "free"})[0], 403)
        # The record endpoint returns an HTML 403, just as before.
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.base + "/api/learning-record", data=b"{}", headers={"X-Session-Token": "test-token"}))
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        set_learning_mode(self.directory, "free")
        self.assertEqual(self.request("/api/initial-state?module=02-graphs", mode="free")[0], 200)
        self.assertFalse((self.directory / "free-learning-record.json").exists())

    def test_cli_switch_and_legacy_defaults(self):
        original = (self.directory / "learning-record.json").read_bytes()
        state = build_initial_state(self.root, "algorithms", SCRIPT_DIR)
        self.assertEqual(state["learning_mode"], "guided")
        for mode in ("free", "guided", "free"):
            subprocess.run([sys.executable, str(SCRIPT_DIR / "set-learning-mode.py"), str(self.directory), mode], check=True, capture_output=True)
            self.assertEqual(build_initial_state(self.root, "algorithms", SCRIPT_DIR)["learning_mode"], mode)
        self.assertEqual((self.directory / "learning-record.json").read_bytes(), original)

    def test_revision_progress_is_pending_in_both_modes_without_resetting_files(self):
        for filename in ("learning-record.json", "free-learning-record.json"):
            record = default_learning_record("algorithms", "2026-11-06T01:00:00Z")
            record["pages"] = [
                {"module": "01-arrays", "section": "01-intro", "completed_at": "before"},
                {"module": "02-graphs", "section": "01-intro", "completed_at": "before"},
            ]
            record["exercises"] = [{"module": "02-graphs", "section": "01-intro", "id": "old", "user_answer": "B"}]
            write_json(self.directory / filename, record)
        originals = {name: (self.directory / name).read_bytes() for name in (
            "learning-record.json", "free-learning-record.json", "domain-tree.json",
        )}
        review = {"schema_version": 5, "course_slug": "algorithms", "items": [{
            "id": "R1", "reason": "目标改变", "previous": [{"module": "02-graphs", "guided_status": "已读"}],
            "targets": [{"module": "02-graphs", "section": "01-intro"}], "decision": None,
        }]}
        write_json(self.directory / "progress-review.json", review)
        meta = json.loads((self.directory / "meta.json").read_text(encoding="utf-8"))
        meta["completed_modules"] = ["01-arrays", "02-graphs"]
        write_json(self.directory / "meta.json", meta)
        self.start_server()
        _, library = self.request("/api/courses")
        self.assertEqual(library["courses"][0]["completed_modules"], 1)
        for mode in ("guided", "free"):
            set_learning_mode(self.directory, mode)
            status, state = self.request("/api/initial-state?module=02-graphs", mode=mode)
            self.assertEqual(status, 200)  # Pending confirmation remains readable.
            self.assertEqual(state["progress_review"]["items"][0]["id"], "R1")
            self.assertEqual(state["domain_tree"]["nodes"]["02-graphs"]["status"], "pending_confirmation")
            self.assertEqual(state["learning_record"]["pages"][0]["completed_at"], "before")
            self.assertNotIn("completed_at", state["learning_record"]["pages"][1])
            self.assertEqual(state["learning_record"]["exercises"], [])
            self.assertEqual(state["meta"]["completed_modules"], ["01-arrays"])
        for filename, original in originals.items():
            self.assertEqual((self.directory / filename).read_bytes(), original)
        review["items"][0]["decision"] = "保留原进度"
        write_json(self.directory / "progress-review.json", review)
        _, state = self.request("/api/initial-state", mode="free")
        self.assertEqual(state["learning_record"]["pages"][1]["completed_at"], "before")
        self.assertEqual(state["learning_record"]["exercises"][0]["user_answer"], "B")

    def test_standalone_server_opens_library_without_course_or_agent(self):
        process = subprocess.Popen([
            sys.executable, str(VIEWER_DIR / "server.py"), "--learning-root", str(self.root), "--no-browser",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            lines = [process.stdout.readline() for _ in range(5)]
            url = next(line.split("url: ", 1)[1].strip() for line in lines if "url: " in line)
            base, token = url.split("#token=")
            with urlopen(base + "api/courses?token=" + token, timeout=5) as response:
                self.assertEqual(json.load(response)["courses"][0]["slug"], "algorithms")
        finally:
            process.terminate()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
