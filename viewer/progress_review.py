"""Project unresolved revision progress without changing the learner's saved state."""

from copy import deepcopy


def pending_items(review: dict) -> list:
    return [item for item in review.get("items", []) if item.get("decision") is None]


def pending_modules(review: dict) -> set:
    return {
        target["module"]
        for item in pending_items(review)
        for target in item.get("targets", []) + item.get("previous", [])
        if target.get("module")
    }


def target_pending(review: dict, module: str, section: str | None = None) -> bool:
    return any(
        target.get("module") == module
        and (not target.get("section") or target.get("section") == section)
        for item in pending_items(review)
        for target in item.get("targets", [])
    )


def effective_record(record: dict, review: dict) -> dict:
    result = deepcopy(record)
    for page in result.get("pages", []):
        if target_pending(review, page.get("module"), page.get("section")):
            page.pop("completed_at", None)
    for field in ("exercises", "legacy_checkpoints", "completions"):
        result[field] = [
            item for item in result.get(field, [])
            if not target_pending(review, item.get("module"), item.get("section"))
        ]
    return result


def apply_progress_review(state: dict, review: dict) -> None:
    state["progress_review"] = review
    affected_modules = pending_modules(review)
    state["learning_record"] = effective_record(state["learning_record"], review)
    state["meta"]["completed_modules"] = [
        module for module in state["meta"].get("completed_modules", [])
        if module not in affected_modules
    ]
    for node_id, node in state["domain_tree"].get("nodes", {}).items():
        if (node.get("module") or node_id) in affected_modules:
            node["status"] = "pending_confirmation"
