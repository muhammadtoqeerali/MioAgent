"""Safe metadata-only model and skill discovery for MioAgent.

No model launches, downloads, external skill instructions, shell commands, or GPU
allocations occur here. Decisions are recommendations, not tool grants.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Role = Literal["chat", "coding", "planning", "review", "research", "diagram"]


@dataclass(frozen=True)
class ModelCandidate:
    model_id: str
    provider: str
    roles: tuple[Role, ...]
    availability: Literal["deployed", "candidate", "research_only"]
    relative_size: Literal["small", "medium", "very_large"]
    verified_source: str
    note: str


@dataclass(frozen=True)
class SkillCandidate:
    skill_id: str
    source: str
    roles: tuple[Role, ...]
    kind: Literal["instruction", "external_tool", "catalog"]
    review_status: Literal["pending"] = "pending"


MODELS: tuple[ModelCandidate, ...] = (
    ModelCandidate(
        "gpt-oss:20b", "ollama", ("chat", "coding", "planning", "review"),
        "deployed", "medium", "https://ollama.com/library/gpt-oss",
        "Already verified on primary workstation; default until benchmarks replace it.",
    ),
    ModelCandidate(
        "qwen3:8b", "ollama", ("chat", "coding", "planning", "research"),
        "candidate", "small", "https://huggingface.co/Qwen/Qwen3-8B",
        "Qwen3-8B candidate; install only after an opt-in and quality benchmark.",
    ),
    ModelCandidate(
        "zai-org/GLM-5.2", "external_research", ("coding", "planning", "review"),
        "research_only", "very_large", "https://huggingface.co/zai-org/GLM-5.2",
        "~753B parameters; do not schedule on current GPUs.",
    ),
)

SKILLS: tuple[SkillCandidate, ...] = (
    SkillCandidate("find-skills", "https://github.com/vercel-labs/skills", ("research",), "catalog"),
    SkillCandidate("chief-of-staff", "https://github.com/mattpocock/skills", ("planning",), "instruction"),
    SkillCandidate("anatomy", "https://github.com/wheresryan22/anatomy", ("diagram",), "instruction"),
    SkillCandidate("teach", "https://skills.sh/paololeonardi/mattpocock-skills/teach", ("research",), "instruction"),
    SkillCandidate("ponytail", "https://github.com/DietrichGebert/ponytail", ("coding", "planning"), "instruction"),
    SkillCandidate("rtk", "https://github.com/rtk-ai/rtk", ("coding",), "external_tool"),
    SkillCandidate("graphify", "https://github.com/deco31416/graphify", ("research", "coding"), "external_tool"),
    SkillCandidate("omniroute", "https://github.com/diegosouzapw/OmniRoute", ("planning",), "external_tool"),
    SkillCandidate("ecc-curated", "https://github.com/affaan-m/ECC", ("coding", "planning", "review"), "catalog"),
)


@dataclass(frozen=True)
class Budget:
    local_gpu_count: int = 1
    remote_gpu_count: int = 0
    cloud_spend_usd: int = 0
    max_skills_per_task: int = 2

    def validate(self) -> None:
        if not 0 <= self.local_gpu_count <= 1:
            raise ValueError("Initial policy allows at most one workstation GPU")
        if not 0 <= self.remote_gpu_count <= 0:
            raise ValueError("University GPU scheduling remains disabled")
        if self.cloud_spend_usd != 0:
            raise ValueError("Paid API routing is disabled")
        if not 0 <= self.max_skills_per_task <= 3:
            raise ValueError("At most three task skills")


def recommend(
    role: Role,
    *,
    installed_models: tuple[str, ...] = ("gpt-oss:20b",),
    audited_skills: frozenset[str] = frozenset(),
    budget: Budget | None = None,
) -> dict:
    """Recommend only installed models and separately audited skills.

    The caller MUST verify installed models and audited skill digests externally.
    This function never grants execution, browser, remote-server, or API access.
    """
    budget = Budget() if budget is None else budget
    budget.validate()
    valid_roles = {"chat", "coding", "planning", "review", "research", "diagram"}
    if role not in valid_roles:
        raise ValueError("Unsupported role")
    if not isinstance(installed_models, tuple) or any(not isinstance(x, str) for x in installed_models):
        raise ValueError("Installed models must be explicit IDs")
    candidates = [m for m in MODELS if m.model_id in installed_models and role in m.roles
                  and m.availability != "research_only"]
    # This is NOT a score or a quality claim. Prefer the confirmed working model
    # until representative evaluations justify a different default.
    candidates.sort(key=lambda m: (m.availability != "deployed", m.model_id))
    model = candidates[0] if candidates and budget.local_gpu_count else None
    matching = [s for s in SKILLS if s.skill_id in audited_skills and role in s.roles
                and s.kind == "instruction"]
    return {
        "role": role,
        "model": model.model_id if model else None,
        "provider": model.provider if model else None,
        "selected_skills": [s.skill_id for s in matching[:budget.max_skills_per_task]],
        "requires_approval_for_any_tool_execution": True,
        "skills_are_untrusted_metadata_only": True,
        "budget": asdict(budget),
        "note": "Routing proposal only; not an execution authorization or quality ranking.",
    }


def inventory() -> dict:
    return {
        "models": [asdict(x) for x in MODELS],
        "skills": [asdict(x) for x in SKILLS],
        "note": "Candidate listings do not mean downloaded, installed, trusted or executable.",
    }
