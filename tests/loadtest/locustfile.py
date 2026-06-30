from locust import HttpUser, task, between
import random


CHAT_ENDPOINT = "/api/v1/chat/completion"

PROMPTS = [
    [{"role": "user", "content": "What is the capital of France?"}],
    [{"role": "user", "content": "Explain quantum entanglement in one sentence."}],
    [
        {"role": "user", "content": "What is 2 + 2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "And what is 4 * 4?"},
    ],
    [{"role": "user", "content": "Name three programming languages."}],
    [{"role": "user", "content": "What is the speed of light?"}],
    [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
        {"role": "user", "content": "What is it known for?"},
    ],
]


def _post(client, key: str, model: str, stream: bool = True):
    client.post(
        CHAT_ENDPOINT,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": random.choice(PROMPTS),
            "stream": stream,
        },
    )


# team-alpha: gpt-4o, gpt-4o-mini  (rate_limit 100, budget $50)
class AlphaUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task(3)
    def gpt4o_stream(self):
        _post(self.client, "loadtest-key-alpha-001", "gpt-4o", stream=True)

    @task(2)
    def gpt4o_mini_stream(self):
        _post(self.client, "loadtest-key-alpha-001", "gpt-4o-mini", stream=True)

    @task(1)
    def gpt4o_no_stream(self):
        _post(self.client, "loadtest-key-alpha-001", "gpt-4o", stream=False)


# team-beta: gpt-4o-mini, claude-sonnet-4-6  (rate_limit 200, budget $100)
class BetaUser(HttpUser):
    wait_time = between(0.5, 2)

    @task(3)
    def gpt4o_mini_stream(self):
        _post(self.client, "loadtest-key-beta-002", "gpt-4o-mini", stream=True)

    @task(3)
    def claude_stream(self):
        _post(self.client, "loadtest-key-beta-002", "claude-sonnet-4-6", stream=True)

    @task(1)
    def claude_no_stream(self):
        _post(self.client, "loadtest-key-beta-002", "claude-sonnet-4-6", stream=False)


# team-gamma: gpt-4o, claude-sonnet-4-6, gemini-2.0-flash  (rate_limit 500, budget $200)
class GammaUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task(3)
    def gpt4o_stream(self):
        _post(self.client, "loadtest-key-gamma-003", "gpt-4o", stream=True)

    @task(3)
    def claude_stream(self):
        _post(self.client, "loadtest-key-gamma-003", "claude-sonnet-4-6", stream=True)

    @task(3)
    def gemini_stream(self):
        _post(self.client, "loadtest-key-gamma-003", "gemini-2.0-flash", stream=True)

    @task(1)
    def gpt4o_no_stream(self):
        _post(self.client, "loadtest-key-gamma-003", "gpt-4o", stream=False)

    @task(1)
    def gemini_no_stream(self):
        _post(self.client, "loadtest-key-gamma-003", "gemini-2.0-flash", stream=False)
