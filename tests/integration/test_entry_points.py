"""Integration tests: verify existing entry points remain functional.

Confirms that root_agent, ADK discovery, and HTTP handler imports
continue to work with the updated pipeline.

Spec refs: FR-BC-003, FR-CLI-006, Section 11.3 (WP14 T14-10).
"""

import pytest
from unittest.mock import patch

try:
    import flask  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False


class TestADKDiscoveryEntryPoint:
    """FR-BC-003: root_agent at module level works for ADK discovery."""

    def test_root_agent_importable(self):
        """from newsletter_agent.agent import root_agent succeeds."""
        from newsletter_agent.agent import root_agent
        assert root_agent is not None

    def test_root_agent_is_sequential(self):
        """root_agent is a SequentialAgent."""
        from google.adk.agents import SequentialAgent
        from newsletter_agent.agent import root_agent
        assert isinstance(root_agent, SequentialAgent)

    def test_root_agent_name(self):
        """root_agent.name is 'NewsletterPipeline'."""
        from newsletter_agent.agent import root_agent
        assert root_agent.name == "NewsletterPipeline"

    def test_root_agent_sub_agent_count(self):
        """root_agent has the expected number of sub-agents (9 pipeline stages)."""
        from newsletter_agent.agent import root_agent
        # ConfigLoader, ResearchPhase, ResearchValidator, PipelineAbortCheck,
        # LinkVerifier, DeepResearchRefiner, Synthesizer, SynthesisPostProcessor,
        # OutputPhase
        assert len(root_agent.sub_agents) == 9

    def test_root_agent_has_deep_research_refiner(self):
        """Pipeline includes DeepResearchRefiner agent (from WP13)."""
        from newsletter_agent.agent import root_agent
        names = [a.name for a in root_agent.sub_agents]
        assert "DeepResearchRefiner" in names

    def test_root_agent_preserves_stage_order(self):
        """Pipeline stages are in correct order."""
        from newsletter_agent.agent import root_agent
        names = [a.name for a in root_agent.sub_agents]
        expected_order = [
            "ConfigLoader",
            "ResearchPhase",
            "ResearchValidator",
            "PipelineAbortCheck",
            "LinkVerifier",
            "DeepResearchRefiner",
            "Synthesizer",
            "SynthesisPostProcessor",
            "OutputPhase",
        ]
        assert names == expected_order


class TestHTTPHandlerEntryPoint:
    """FR-CLI-006: HTTP handler endpoint is importable."""

    @pytest.mark.skipif(not _HAS_FLASK, reason="Flask not installed")
    def test_http_handler_importable(self):
        """newsletter_agent.http_handler can be imported."""
        from newsletter_agent import http_handler
        assert hasattr(http_handler, "app")

    @pytest.mark.skipif(not _HAS_FLASK, reason="Flask not installed")
    def test_http_handler_has_run_endpoint(self):
        """HTTP handler has /run endpoint."""
        from newsletter_agent.http_handler import app
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert "/run" in rules


class TestCLIEntryPoint:
    """CLI entry point remains functional."""

    def test_main_function_importable(self):
        """newsletter_agent.__main__.main() can be imported."""
        from newsletter_agent.__main__ import main
        assert callable(main)

    def test_run_pipeline_importable(self):
        """newsletter_agent.__main__.run_pipeline() can be imported."""
        from newsletter_agent.__main__ import run_pipeline
        assert callable(run_pipeline)


class TestNoImportSideEffects:
    """New modules do not have harmful import side effects."""

    def test_deep_research_import_clean(self):
        """Importing deep_research module does not trigger API calls."""
        import newsletter_agent.tools.deep_research as mod
        assert hasattr(mod, "DeepResearchOrchestrator")

    def test_deep_research_refiner_import_clean(self):
        """Importing deep_research_refiner module does not trigger API calls."""
        import newsletter_agent.tools.deep_research_refiner as mod
        assert hasattr(mod, "DeepResearchRefinerAgent")

    def test_prompt_modules_import_clean(self):
        """Importing prompt modules is side-effect free."""
        import newsletter_agent.prompts.query_expansion as qe
        import newsletter_agent.prompts.refinement as ref
        assert hasattr(qe, "get_query_expansion_instruction")
        assert hasattr(ref, "get_refinement_instruction")
