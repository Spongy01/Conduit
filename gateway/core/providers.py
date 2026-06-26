import os
from gateway.providers.OpenAIProvider import OpenAIProvider
from gateway.providers.AnthropicProvider import AnthropicProvider
from gateway.providers.OllamaProvider import OllamaProvider
from gateway.providers.GeminiProvider import GeminiProvider
from dotenv import load_dotenv
load_dotenv()

PROVIDERS = {
    "openai": OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"]),
    "anthropic": AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"]),
    "ollama": OllamaProvider(base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")),
    "gemini": GeminiProvider(api_key=os.environ["GEMINI_API_KEY"]),
}
