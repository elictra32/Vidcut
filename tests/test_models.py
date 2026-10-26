from core.models import Project, project_from_dict, project_to_dict
from core.presets import PRESETS


def test_default_project_style_matches_default_preset():
    p = Project()
    overrides = PRESETS[p.preset].style_overrides
    assert p.style.size == overrides["size"]
    assert p.style.default_y == overrides["default_y"]


def test_project_dict_roundtrip_keeps_style():
    p = Project()
    assert project_from_dict(project_to_dict(p)) == p
