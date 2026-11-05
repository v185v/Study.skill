"""Learning access policy and independent reading records for each policy."""

from pathlib import Path

from utils import load_json, write_json_atomic


LEARNING_MODES = {"guided", "free"}


def learning_mode(meta: dict) -> str:
    mode = meta.get("learning_mode", "guided")
    if mode not in LEARNING_MODES:
        raise ValueError(f"unknown learning_mode: {mode}")
    return mode


def learning_record_path(course_state_dir: Path, mode: str) -> Path:
    if mode not in LEARNING_MODES:
        raise ValueError(f"unknown learning_mode: {mode}")
    filename = "free-learning-record.json" if mode == "free" else "learning-record.json"
    return course_state_dir / filename


def set_learning_mode(course_state_dir: Path, mode: str) -> dict:
    if mode not in LEARNING_MODES:
        raise ValueError(f"unknown learning_mode: {mode}")
    path = course_state_dir / "meta.json"
    meta = load_json(path)
    if meta.get("generation_status") != "complete":
        raise PermissionError("course generation is not complete")
    if learning_mode(meta) != mode:
        meta["learning_mode"] = mode
        write_json_atomic(path, meta)
    return meta
