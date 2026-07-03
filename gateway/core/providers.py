"""Instantiates one provider client per upstream LLM API, keyed by name.
router.py looks models up here after resolving which provider owns them."""
import os
from gateway.providers.OpenAIProvider import OpenAIProvider
from gateway.providers.AnthropicProvider import AnthropicProvider
from gateway.providers.OllamaProvider import OllamaProvider
from gateway.providers.GeminiProvider import GeminiProvider
from dotenv import load_dotenv
load_dotenv()

# Singletons reused across requests, keyed by the provider name stored
# against each model in the catalog (see core/team_config.py enrichment).
PROVIDERS = {
    "openai": OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"]),
    "anthropic": AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"]),
    "ollama": OllamaProvider(base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")),
    "gemini": GeminiProvider(api_key=os.environ["GEMINI_API_KEY"]),
}
