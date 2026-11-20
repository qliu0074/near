import hashlib
import json
import math
import unicodedata
from fastapi import HTTPException
from .billing import metered
from .failures import report


def embedding(factory, settings, provider, owner, companion, text, key):
    fingerprint = hashlib.sha256((settings.embedding_model + ':' + str(settings.embedding_dims) + ':' + text).encode()).hexdigest()
    return metered(factory, settings, owner, companion, 'embedding', key + fingerprint,
        len(text.encode('utf-8')) + 128, lambda: provider.embed_with_usage(text))


def query_embedding(factory, settings, provider, owner, companion, text, request_id):
    if settings.provider != 'qwen' or not settings.embedding_model:
        return None
    return embedding(factory, settings, provider, owner, companion, text, 'query:' + request_id)


def rank_memories(factory, settings, provider, owner, companion, query, request_id, memories, *, limit=True):
    """Rerank only database-authorized rows, preserving RRF order on safe failure."""
    unique, seen_ids, seen_text = [], set(), set()
    for memory in memories:
        content = memory.content[:400]
        normalized = ' '.join(unicodedata.normalize('NFKC', content).split()).casefold()
        if not normalized or memory.id in seen_ids or normalized in seen_text:
            continue
        seen_ids.add(memory.id)
        seen_text.add(normalized)
        unique.append(memory)
    fallback = unique[:settings.memory_limit] if limit else unique
    if not settings.rerank_enabled or settings.provider != 'qwen' or len(unique) < 2:
        return fallback
    # Conservative byte bounds also cover gte-rerank-v2's 30k request limit.
    # Query tokens are billed once per document. Do not silently truncate queries.
    query_bytes = len(query.encode('utf-8'))
    candidates, documents, amount = [], [], 256
    if query_bytes > 4000:
        return fallback
    for memory in unique[:settings.rerank_candidates]:
        content = memory.content[:400]
        cost = query_bytes + len(content.encode('utf-8'))
        if amount + cost > 30000:
            break
        amount += cost
        candidates.append(memory)
        documents.append(content)
    if len(candidates) < 2:
        return fallback
    fingerprint = hashlib.sha256(json.dumps([settings.rerank_url, settings.rerank_model, query,
        [(m.id, m.version, text) for m, text in zip(candidates, documents)]],
        ensure_ascii=False).encode()).hexdigest()
    try:
        result = metered(factory, settings, owner, companion, 'rerank', request_id + ':' + fingerprint,
            amount, lambda: provider.rerank_with_usage(query, documents))
    except HTTPException as error:
        if error.status_code != 503:
            # Uncertain/pending paid calls retain their reservations; never hide
            # those failures or begin another paid chat on top of them.
            raise
        report('rerank_unavailable', request_id, error)
        return fallback
    try:
        results = result['results']
        if not isinstance(results, list) or not results or len(results) > len(candidates):
            raise ValueError('Invalid rerank result count')
        scores = {}
        for item in results:
            index, score = item['index'], item['relevance_score']
            if (type(index) is not int or not 0 <= index < len(candidates) or index in scores
                    or type(score) not in (int, float) or not 0 <= score <= 1 or not math.isfinite(score)):
                raise ValueError('Invalid rerank index or score')
            scores[index] = score
        ranked = [candidates[i] for i in sorted(scores, key=lambda i: (-scores[i], i))]
        ranked_ids = {m.id for m in ranked}
        ranked.extend(m for m in unique if m.id not in ranked_ids)
        return ranked[:settings.memory_limit] if limit else ranked
    except (KeyError, TypeError, ValueError) as error:
        report('rerank_invalid', request_id, error)
        return fallback
