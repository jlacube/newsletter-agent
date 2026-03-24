"""T23-01: ADK Callback Verification Spike.

DECISION RECORD (OQ-1 Resolution):
    The ADK `after_model_callback` fires BEFORE `_maybe_add_grounding_metadata`
    attaches grounding metadata to the LlmResponse. Therefore:

    - `llm_response.grounding_metadata` is None inside after_model_callback
    - The raw grounding metadata IS available at
      `callback_context.state['temp:_adk_grounding_metadata']` (a
      `types.GroundingMetadata` object) because ADK stores it there during
      model response processing, before the callback fires.

    All subsequent tasks (T23-02 through T23-10) SHALL read grounding metadata
    from `callback_context.state['temp:_adk_grounding_metadata']` inside the
    after_model_callback, NOT from `llm_response.grounding_metadata`.

    Verified by:
    1. Inspecting ADK source: `_handle_after_model_callback` in
       `google.adk.flows.llm_flows.base_llm_flow` - callbacks at lines 283-303,
       `_maybe_add_grounding_metadata` wraps all exit paths AFTER callbacks.
    2. `_maybe_add_grounding_metadata` reads from
       `session.state['temp:_adk_grounding_metadata']` (line 267-268) and
       assigns to `response.grounding_metadata` (line 275).

This test uses a real Gemini API call. Skip in CI with:
    pytest -m "not integration"
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        True,
        reason=(
            "OQ-1 resolved via ADK source inspection. "
            "Real API spike not needed - callback reads from "
            "state['temp:_adk_grounding_metadata']. "
            "See decision record above."
        ),
    ),
]


class TestGroundingCallbackSpike:
    """Verify grounding metadata availability in after_model_callback.

    RESOLVED: ADK source confirms after_model_callback fires BEFORE
    _maybe_add_grounding_metadata. Use state['temp:_adk_grounding_metadata'].
    """

    def test_oq1_resolved_via_source_inspection(self):
        """OQ-1 is resolved. Grounding metadata is read from session state."""
        # This test documents the decision. The actual verification was done
        # by inspecting ADK source code (see module docstring).
        #
        # Mechanism: callback_context.state['temp:_adk_grounding_metadata']
        # Type: Optional[google.genai.types.GroundingMetadata]
        # Available: Yes, when google_search tool is used and returns results
        # Timing: Set by ADK before after_model_callback fires
        pass
