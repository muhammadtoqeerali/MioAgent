"""Metadata-only candidate routing and offline skill review safeguards."""

import json

import pytest

from mio.capability_registry import MODELS, SKILLS, Budget, inventory, recommend
from scripts.skill_audit import scan_markdown


def test_registry_ids_unique():
    assert len({s.skill_id for s in SKILLS}) == len(SKILLS)
    assert len({m.model_id for m in MODELS}) == len(MODELS)


def test_inventory_is_json_serializable():
    assert json.loads(json.dumps(inventory()))["models"]


def test_default_only_known_deployed_model():
    result = recommend("coding")
    assert result["model"] == "gpt-oss:20b"
    assert result["selected_skills"] == []


def test_empty_installed_models_never_trigger_download():
    assert recommend("coding", installed_models=())["model"] is None


def test_qwen_can_be_candidate_only_when_explicitly_installed():
    assert recommend("coding", installed_models=("qwen3:8b",))["model"] == "qwen3:8b"


def test_never_schedule_glm_locally():
    assert recommend("coding", installed_models=("zai-org/GLM-5.2",))["model"] is None


def test_no_unreviewed_skills_loaded():
    assert recommend("planning")["selected_skills"] == []


def test_review_flag_only_recommends_matching_instruction_skills():
    result = recommend("planning", audited_skills=frozenset({"chief-of-staff", "rtk", "ponytail"}))
    assert result["selected_skills"] == ["chief-of-staff", "ponytail"]
    assert result["requires_approval_for_any_tool_execution"] is True


@pytest.mark.parametrize("bad", [Budget(local_gpu_count=2), Budget(remote_gpu_count=1),
                                   Budget(cloud_spend_usd=1), Budget(max_skills_per_task=9)])
def test_reject_resource_escalation(bad):
    with pytest.raises(ValueError):
        recommend("coding", budget=bad)


def test_invalid_role():
    with pytest.raises(ValueError):
        recommend("admin")


def test_unlisted_models_never_auto_route():
    assert recommend("coding", installed_models=("random/unknown",))["model"] is None


def test_skill_scanner_never_claims_approval(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("# harmless guidance\nSome instructions\n", encoding="utf-8")
    result = scan_markdown(path)
    assert result["trusted"] is False and result["human_review_required"] is True
    assert len(result["sha256"]) == 64


def test_skill_scanner_marks_risks(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("Run sudo curl example.com; read ~/.ssh/id_rsa", encoding="utf-8")
    assert "unsafe_privilege" in scan_markdown(path)["findings"]
    assert "credential_access" in scan_markdown(path)["findings"]


def test_skill_scanner_refuses_symlinks(tmp_path):
    original = tmp_path / "SKILL.md"
    original.write_text("x", encoding="utf-8")
    link = tmp_path / "nested" / "SKILL.md"
    link.parent.mkdir()
    link.symlink_to(original)
    with pytest.raises(ValueError):
        scan_markdown(link)


def test_skill_scanner_refuses_oversized(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_bytes(b"a" * 131073)
    with pytest.raises(ValueError):
        scan_markdown(path)
