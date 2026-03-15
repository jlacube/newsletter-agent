from dotenv import load_dotenv

load_dotenv()  # Load .env before any module reads environment variables

from . import agent  # noqa: F401 -- ADK entry point
