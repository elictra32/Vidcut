"""project.json persistence. Writes are atomic (temp file + os.replace)."""
import json
import os

from core.models import Project, project_from_dict, project_to_dict

FILENAME = "project.json"


def default_home() -> str:
    return os.environ.get("VIDCUT_HOME") or os.path.join(os.path.expanduser("~"), "VidcutProjects", "default")


def load_project(dir: str) -> Project:
    path = os.path.join(dir, FILENAME)
    if not os.path.exists(path):
        return Project()
    with open(path, encoding="utf-8") as f:
        return project_from_dict(json.load(f))


def save_project(project: Project, dir: str) -> None:
    os.makedirs(dir, exist_ok=True)
    path, tmp = os.path.join(dir, FILENAME), os.path.join(dir, FILENAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(project_to_dict(project), f, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
