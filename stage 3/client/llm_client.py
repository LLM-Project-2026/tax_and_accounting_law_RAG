import json

from openai import OpenAI


def load_secrets(path="secrets.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class LLMClient:
    """Thin wrapper around an OpenAI-compatible chat completions API."""

    def __init__(self, api_key, base_url, model):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages):
        """Stream a chat completion. Yields content chunks as they arrive."""
        stream = self.client.chat.completions.create(
            model=self.model,
            
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
