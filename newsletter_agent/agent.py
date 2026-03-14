from google.adk.agents import LlmAgent

root_agent = LlmAgent(
    name="newsletter_agent",
    model="gemini-2.5-flash",
    instruction="You are the Newsletter Agent. The pipeline is not yet wired.",
)
