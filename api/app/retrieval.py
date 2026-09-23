import hashlib
import time
from .billing import metered


def embedding(factory, settings, provider, owner, companion, text, key):
    fingerprint = hashlib.sha256((settings.embedding_model + ':' + str(settings.embedding_dims) + ':' + text).encode()).hexdigest()
    return metered(factory, settings, owner, companion, 'embedding', key + fingerprint,
        len(text.encode('utf-8')) + 128, lambda: provider.embed_with_usage(text))


def query_embedding(factory, settings, provider, owner, companion, text, request_id):
    if settings.provider != 'qwen' or not settings.embedding_model:
        return None
    return embedding(factory, settings, provider, owner, companion, text, 'query:' + request_id)
