import json
import math
from dataclasses import dataclass
from collections.abc import Iterator
import httpx
from .config import Settings
from .failures import provider_client, async_provider_client


@dataclass
class Reply:
    text: str
    tokens: int


def estimate_input(messages: list[dict[str, str]]) -> int:
    # Conservative byte-based fallback, NOT a model-exact tokenizer.
    # Include serialized role delimiters and safety overhead exactly once.
    return len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 256


class Provider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, messages: list[dict[str, str]]) -> Reply:
        if self.settings.provider == 'mock':
            text = '[Local demo] I am here to listen. Would you like to share a little more about your day?'
            return Reply(text, estimate_input(messages) + len(text.encode('utf-8')))
        with provider_client(self.settings.provider_timeout) as client:
            response = client.post(self.settings.qwen_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': f'Bearer {self.settings.qwen_key}'},
                json={'model': self.settings.chat_model, 'messages': messages,
                      'max_tokens': self.settings.max_output, 'stream': False,
                      'enable_thinking': False})
            response.raise_for_status()
            body = response.json()
        text = body['choices'][0]['message']['content']
        tokens = body['usage']['total_tokens']
        if not isinstance(text, str) or not text.strip() or not isinstance(tokens, int) or tokens < 0:
            raise ValueError('Invalid provider output or usage')
        return Reply(text, tokens)

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str | Reply]:
        if self.settings.provider == 'mock':
            reply = self.complete(messages)
            for start in range(0, len(reply.text), 5):
                yield reply.text[start:start+5]
            yield reply
            return
        parts: list[str] = []
        tokens: int | None = None
        finished = False
        with provider_client(self.settings.provider_timeout) as client:
            with client.stream('POST', self.settings.qwen_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': f'Bearer {self.settings.qwen_key}'},
                json={'model': self.settings.chat_model, 'messages': messages,
                      'max_tokens': self.settings.max_output, 'stream': True,
                      'stream_options': {'include_usage': True}, 'enable_thinking': False}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        finished = True
                        break
                    body = json.loads(data)
                    if body.get('usage'):
                        tokens = body['usage']['total_tokens']
                    for choice in body.get('choices', []):
                        content = choice.get('delta', {}).get('content')
                        if content:
                            if not isinstance(content, str):
                                raise ValueError('Invalid delta')
                            parts.append(content)
                            if sum(len(part) for part in parts) > 20000:
                                raise ValueError('Output safety limit')
                            yield content
        if not finished or not isinstance(tokens, int) or tokens < 0 or not parts:
            raise ValueError('Incomplete response or missing usage')
        yield Reply(''.join(parts), tokens)

    def embed(self, text: str) -> list[float]:
        return self.embed_with_usage(text)[0]

    def embed_with_usage(self, text: str) -> tuple[list[float], int]:
        if self.settings.provider != 'qwen' or not self.settings.embedding_model:
            raise ValueError('Embedding is not configured; no fake semantic vectors')
        with provider_client(20) as client:
            response = client.post(self.settings.qwen_url.rstrip('/') + '/embeddings',
                headers={'Authorization': f'Bearer {self.settings.qwen_key}'},
                json={'model': self.settings.embedding_model, 'input': text,
                      'dimensions': self.settings.embedding_dims})
            response.raise_for_status()
            body = response.json()
            vector = body['data'][0]['embedding']
            usage = body['usage']['total_tokens']
        if len(vector) != self.settings.embedding_dims or not isinstance(usage, int) or usage < 0:
            raise ValueError('Embedding dimension mismatch')
        result = [float(v) for v in vector]
        if not all(math.isfinite(v) for v in result) or not any(v != 0 for v in result):
            raise ValueError('Invalid embedding values')
        return result, usage

    async def astream(self, messages: list[dict[str, str]]):
        if self.settings.provider == 'mock':
            reply = self.complete(messages)
            for start in range(0, len(reply.text), 5):
                yield reply.text[start:start+5]
            yield reply
            return
        parts: list[str] = []
        tokens: int | None = None
        finished = False
        async with async_provider_client(self.settings.provider_timeout) as client:
            async with client.stream('POST', self.settings.qwen_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': f'Bearer {self.settings.qwen_key}'},
                json={'model': self.settings.chat_model, 'messages': messages,
                      'max_tokens': self.settings.max_output, 'stream': True,
                      'stream_options': {'include_usage': True}, 'enable_thinking': False}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        finished = True
                        break
                    body = json.loads(data)
                    if body.get('usage'):
                        tokens = body['usage']['total_tokens']
                    for choice in body.get('choices', []):
                        content = choice.get('delta', {}).get('content')
                        if content:
                            if not isinstance(content, str):
                                raise ValueError('Invalid delta')
                            parts.append(content)
                            if sum(len(part) for part in parts) > 20000:
                                raise ValueError('Output safety limit')
                            yield content
        if not finished or not isinstance(tokens, int) or tokens < 0 or not parts:
            raise ValueError('Incomplete response or missing usage')
        yield Reply(''.join(parts), tokens)
