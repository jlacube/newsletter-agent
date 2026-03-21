from dotenv import load_dotenv

load_dotenv()  # Load .env before any module reads environment variables

from .telemetry import init_telemetry

init_telemetry()

from . import agent  # noqa: F401 -- ADK entry point
