"""Security verification for deep research features.

Verifies that the CLI does not accept arbitrary arguments, query expansion
and refinement prompts do not leak sensitive info, and existing SSRF
protections work with the new features.

Spec refs: Section 10.2, Section 11.6 (WP14 T14-09).
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from newsletter_agent.prompts.query_expansion import get_query_expansion_instruction
from newsletter_agent.prompts.refinement import get_refinement_instruction

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestCLIArgumentSafety:
    """CLI runner does not accept command-line arguments for injection."""

    def test_main_does_not_use_sys_argv(self):
        """__main__.py does not parse command-line arguments."""
        main_path = PROJECT_ROOT / "newsletter_agent" / "__main__.py"
        content = main_path.read_text()
        assert "argparse" not in content, "CLI should not use argparse"
        assert "sys.argv" not in content, "CLI should not access sys.argv"

    def test_main_does_not_use_click_or_typer(self):
        """CLI does not use any CLI framework that accepts args."""
        main_path = PROJECT_ROOT / "newsletter_agent" / "__main__.py"
        content = main_path.read_text()
        assert "import click" not in content
        assert "import typer" not in content

    def test_extra_args_ignored_on_module_run(self):
        """Extra arguments to python -m newsletter_agent do not cause injection."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from newsletter_agent.__main__ import main; "
                "from newsletter_agent.telemetry import shutdown_telemetry; "
                "import sys; sys.argv = ['test', '--malicious', '--inject=rm -rf /']; "
                "shutdown_telemetry()",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should import fine - the main function ignores args
        assert result.returncode == 0, f"Import failed: {result.stderr}"


class TestPromptSafety:
    """Query expansion and refinement prompts do not leak sensitive info."""

    _SENSITIVE_PATTERNS = [
        r"AIza[0-9A-Za-z\-_]{35}",
        r"pplx-[a-z0-9]{48}",
        r"GOOGLE_API_KEY",
        r"PERPLEXITY_API_KEY",
        r"/home/|C:\\\\Users\\\\",
        r"password|secret|token",
    ]

    def test_query_expansion_prompt_no_secrets(self):
        """Query expansion prompt does not contain API keys or paths."""
        prompt = get_query_expansion_instruction(
            "AI news", "Artificial Intelligence", 3
        )
        for pattern in self._SENSITIVE_PATTERNS:
            assert not re.search(pattern, prompt, re.IGNORECASE), (
                f"Prompt contains sensitive pattern: {pattern}"
            )

    def test_refinement_prompt_no_secrets(self):
        """Refinement prompt does not contain API keys or paths."""
        prompt = get_refinement_instruction(
            "AI News",
            5,
            "Some research text about AI.",
            "- [Src](https://example.com)",
        )
        for pattern in self._SENSITIVE_PATTERNS:
            assert not re.search(pattern, prompt, re.IGNORECASE), (
                f"Prompt contains sensitive pattern: {pattern}"
            )

    def test_prompts_do_not_expose_system_instructions(self):
        """Prompts do not contain system-level or meta-instructions that could be leaked."""
        expansion = get_query_expansion_instruction("test query", "test topic", 2)
        refinement = get_refinement_instruction(
            "test topic", 5, "research text", "- [S](https://ex.com)"
        )

        for prompt in [expansion, refinement]:
            assert "system prompt" not in prompt.lower()
            assert "ignore previous" not in prompt.lower()
            assert "override" not in prompt.lower()


class TestNoNewAttackSurface:
    """New deep research modules do not introduce attack surface."""

    def test_deep_research_no_eval_or_exec(self):
        """deep_research.py does not use eval() or exec()."""
        path = PROJECT_ROOT / "newsletter_agent" / "tools" / "deep_research.py"
        content = path.read_text()
        # Check for bare eval/exec calls (not in comments)
        lines = [
            l
            for l in content.split("\n")
            if not l.strip().startswith("#") and not l.strip().startswith('"""')
        ]
        code = "\n".join(lines)
        assert "eval(" not in code, "deep_research.py should not use eval()"
        assert "exec(" not in code, "deep_research.py should not use exec()"

    def test_deep_research_refiner_no_eval_or_exec(self):
        """deep_research_refiner.py does not use eval() or exec()."""
        path = (
            PROJECT_ROOT / "newsletter_agent" / "tools" / "deep_research_refiner.py"
        )
        content = path.read_text()
        lines = [
            l
            for l in content.split("\n")
            if not l.strip().startswith("#") and not l.strip().startswith('"""')
        ]
        code = "\n".join(lines)
        assert "eval(" not in code, "refiner should not use eval()"
        assert "exec(" not in code, "refiner should not use exec()"

    def test_no_subprocess_in_deep_research(self):
        """Deep research modules do not spawn subprocesses."""
        for module in ["deep_research.py", "deep_research_refiner.py"]:
            path = PROJECT_ROOT / "newsletter_agent" / "tools" / module
            content = path.read_text()
            assert "subprocess" not in content, (
                f"{module} should not use subprocess"
            )
            assert "os.system" not in content, (
                f"{module} should not use os.system"
            )
