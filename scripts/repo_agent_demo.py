"""Prepare a private, realistic two-file existing-repository repair challenge.

Only creates a fresh isolated fixture under MioAgent's private native runtime.
Does not invoke AI models, modify the source checkout, or run code.
"""

import json

from scripts.native_runtime import RUNTIME, setup_runtime

FIXTURE = {
    "labmetrics/__init__.py": '"""A tiny pre-existing experiment metrics package."""\n',
    "labmetrics/metrics.py": (
        '"""Binary-classification evaluation metrics."""\n'
        'def f1_score(precision: float, recall: float) -> float:\n'
        '    """Return zero if both terms are zero, otherwise harmonic F1."""\n'
        '    return (precision + recall) / 2  # BUG: arithmetic mean\n'
    ),
    "labmetrics/formatting.py": (
        '"""Reporting helpers."""\n'
        'def percent(value: float) -> str:\n'
        '    """Show a proportion with exactly one decimal place."""\n'
        '    return f"{value:.1f}%"  # BUG: omitted times 100\n'
    ),
    "test_metrics.py": (
        "import unittest\nfrom labmetrics.metrics import f1_score\n"
        "class MetricsTests(unittest.TestCase):\n"
        "    def test_perfect(self): self.assertAlmostEqual(f1_score(1, 1), 1.0)\n"
        "    def test_unbalanced(self): self.assertAlmostEqual(f1_score(1, 0.5), 2 / 3)\n"
        "    def test_zero(self): self.assertEqual(f1_score(0, 0), 0.0)\n"
    ),
    "test_formatting.py": (
        "import unittest\nfrom labmetrics.formatting import percent\n"
        "class FormattingTests(unittest.TestCase):\n"
        "    def test_fraction(self): self.assertEqual(percent(0.235), '23.5%')\n"
        "    def test_whole(self): self.assertEqual(percent(1.0), '100.0%')\n"
    ),
}


def main() -> None:
    setup_runtime()
    root = RUNTIME / "repo-engineering-demo"
    if root.exists() or root.is_symlink():
        raise SystemExit("STOP: Demo already exists; preserve previous results")
    root.mkdir(mode=0o700)
    for name, source in FIXTURE.items():
        dest = root / name
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        dest.write_text(source, encoding="utf-8")
        dest.chmod(0o600)
    goal = {
        "repository": str(root),
        "task": ("Fix the existing experimental-metrics code: implement true harmonic F1 "
                 "with correct zero handling and make report percentages convert proportions "
                 "to percentages. Preserve the APIs and pass all original tests."),
        "editable_files": ["labmetrics/metrics.py", "labmetrics/formatting.py"],
        "acceptance_tests": ["test_metrics.py", "test_formatting.py"],
        "max_attempts": 3,
    }
    goal_path = RUNTIME / "repo-engineering-demo-goal.json"
    with goal_path.open("x", encoding="utf-8") as stream:
        json.dump(goal, stream, indent=2)
        stream.write("\n")
    goal_path.chmod(0o600)
    print(json.dumps({"repository": str(root), "goal": str(goal_path),
                      "next": f"python -m scripts.repo_engineer {goal_path} --execute"}, indent=2))


if __name__ == "__main__":
    main()
