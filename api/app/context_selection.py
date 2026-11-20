"""Bounded context packing. Provider-reported usage remains billing authority."""
import json
import math
from dataclasses import dataclass


class TokenCounter:
    def __init__(self, tokenizer_path: str = ''):
        self.tokenizer = None
        if tokenizer_path:
            from tokenizers import Tokenizer
            self.tokenizer = Tokenizer.from_file(tokenizer_path)
            # A saved tokenizer must never silently truncate or pad counts.
            self.tokenizer.no_truncation()
            self.tokenizer.no_padding()

    def count(self, text: str) -> int:
        if self.tokenizer is None:
            return len(text.encode('utf-8'))
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def messages(self, messages: list[dict[str, str]]) -> int:
        # JSON/roles + a margin; this is not the provider's hidden chat template.
        return self.count(json.dumps(messages, ensure_ascii=False)) + 256


@dataclass(frozen=True)
class ContextItem:
    key: str
    text: str
    tokens: int
    utility: float


def _validate(items, budget, max_items):
    if type(budget) is not int or not 0 <= budget <= 8192 or type(max_items) is not int or not 0 <= max_items <= 10:
        raise ValueError('Invalid context budget or item limit')
    if len(items) > 500 or len({item.key for item in items}) != len(items):
        raise ValueError('Context candidates must have unique keys and number at most 500')
    for item in items:
        if (type(item.tokens) is not int or item.tokens <= 0 or not math.isfinite(item.utility)
                or item.utility < 0):
            raise ValueError('Invalid context item cost or utility')


def select_greedy(items: list[ContextItem], budget: int, max_items: int) -> list[ContextItem]:
    """Take highest utility/token ratio first; ties follow retrieval rank."""
    _validate(items, budget, max_items)
    selected, used = [], 0
    for index in sorted(range(len(items)), key=lambda i: (-items[i].utility / items[i].tokens, i)):
        item = items[index]
        if len(selected) < max_items and item.utility > 0 and used + item.tokens <= budget:
            selected.append(index)
            used += item.tokens
    return [items[i] for i in sorted(selected)]


def select_knapsack(items: list[ContextItem], budget: int, max_items: int) -> list[ContextItem]:
    """Exact 0/1 packing with both token and item-count constraints.

    Descending capacity/count updates prevent candidate reuse. Immutable index
    tuples keep reconstruction valid after later states are overwritten.
    """
    _validate(items, budget, max_items)
    if not budget or not max_items:
        return []
    max_items = min(max_items, len(items))
    # O(candidates * max_items * budget) time, O(max_items * budget) states.
    states = [[(0.0, ()) for _ in range(budget + 1)] for _ in range(max_items + 1)]
    for index, item in enumerate(items):
        if item.tokens > budget or item.utility <= 0:
            continue
        for count in range(max_items, 0, -1):
            for capacity in range(budget, item.tokens - 1, -1):
                score, chosen = states[count - 1][capacity - item.tokens]
                candidate = (score + item.utility, chosen + (index,))
                current = states[count][capacity]
                if candidate[0] > current[0] or (candidate[0] == current[0] and candidate[1] < current[1]):
                    states[count][capacity] = candidate
    return [items[i] for i in states[max_items][budget][1]]


def select_memories(memories, settings, counter, base_prompt):
    available = 24000 - settings.max_output - counter.messages(base_prompt)
    budget = max(0, min(settings.memory_token_budget, available))
    items = [ContextItem(memory.id, memory.content[:400],
        # Memories are JSON inside the system message, itself serialized as JSON.
        max(1, counter.count(json.dumps(json.dumps(memory.content[:400], ensure_ascii=False),
            ensure_ascii=False)) + counter.count(', ')),
        1.0 / (rank + 1)) for rank, memory in enumerate(memories)]
    selector = select_knapsack if settings.context_selection == 'dp' else select_greedy
    selected = selector(items, budget, settings.memory_limit)
    keys = {item.key for item in selected}
    return [memory for memory in memories if memory.id in keys]
