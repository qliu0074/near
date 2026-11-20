import itertools
import json
import random
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_api import client, login, companion
from app.config import Settings
from app.context_selection import ContextItem, TokenCounter, select_greedy, select_knapsack, select_memories
from app.models import Memory, User
from app.providers import Reply, estimate_input
from app.search import Search


def item(key, tokens, utility):
    return ContextItem(key, key, tokens, utility)


def test_dp_improves_over_ratio_greedy():
    items = [item('a', 10, 60), item('b', 20, 100), item('c', 30, 120)]
    assert [x.key for x in select_greedy(items, 50, 2)] == ['a', 'b']
    assert [x.key for x in select_knapsack(items, 50, 2)] == ['b', 'c']


@pytest.mark.parametrize('select', [select_greedy, select_knapsack])
def test_empty_zero_exact_fit_oversized_and_count_limit(select):
    assert select([], 10, 2) == []
    items = [item('a', 5, 8), item('b', 4, 6), item('c', 11, 100)]
    assert select(items, 0, 2) == []
    assert select(items, 10, 0) == []
    assert [x.key for x in select(items, 9, 2)] == ['a', 'b']
    assert len(select(items, 9, 1)) == 1
    assert len(select([item('a', 2, 5)], 8, 4)) == 1
    assert select([item('zero', 1, 0)], 8, 4) == []


def test_dp_matches_exhaustive_search_and_never_reuses_items():
    randomizer = random.Random(27)
    for _ in range(50):
        items = [item(str(i), randomizer.randint(1, 12), randomizer.randint(1, 20)) for i in range(7)]
        budget, limit = randomizer.randint(0, 30), randomizer.randint(0, 4)
        expected = max((sum(i.utility for i in subset) for n in range(limit + 1)
            for subset in itertools.combinations(items, n) if sum(i.tokens for i in subset) <= budget), default=0)
        selected = select_knapsack(items, budget, limit)
        assert sum(i.utility for i in selected) == expected
        assert len(selected) == len({i.key for i in selected}) <= limit
        assert sum(i.tokens for i in selected) <= budget


def test_ties_use_retrieval_order():
    items = [item('first', 2, 1), item('second', 2, 1)]
    assert select_knapsack(items, 2, 1) == items[:1]
    assert select_greedy(items, 2, 1) == items[:1]


@pytest.mark.parametrize('select', [select_greedy, select_knapsack])
@pytest.mark.parametrize('items,budget,limit', [
    ([item('a', 0, 1)], 10, 2), ([item('a', 2, float('nan'))], 10, 2),
    ([item('a', 2, 1), item('a', 2, 2)], 10, 2), ([], -1, 2), ([], 8193, 2), ([], 10, 11),
])
def test_invalid_inputs(select, items, budget, limit):
    with pytest.raises(ValueError):
        select(items, budget, limit)


def test_utf8_counter_and_json_overhead():
    counter = TokenCounter()
    assert counter.count('') == 0
    assert counter.count('中文🙂') == len('中文🙂'.encode('utf-8'))
    messages = [{'role': 'user', 'content': '"\\\n中文'}]
    assert counter.messages(messages) == estimate_input(messages)


def test_local_tokenizer_disables_saved_padding_and_truncation(tmp_path):
    from tokenizers import Tokenizer, models, pre_tokenizers
    tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, 'hello': 1, 'world': 2}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.enable_truncation(max_length=1)
    tokenizer.enable_padding(length=10)
    path = tmp_path / 'tokenizer.json'; tokenizer.save(str(path))
    counter = TokenCounter(str(path))
    assert counter.count('hello world hello') == 3
    assert counter.count('') == 0


def test_budgeted_selection_considers_candidates_beyond_top_n():
    rows = [SimpleNamespace(id='big', content='x'*400),
            SimpleNamespace(id='short', content='tea'), SimpleNamespace(id='other', content='apples')]
    settings = replace(Settings(), memory_token_budget=30, memory_limit=1)
    assert select_memories(rows, settings, TokenCounter(), []) == rows[1:2]
    assert select_memories(rows, replace(settings, memory_token_budget=0), TokenCounter(), []) == []
    assert select_memories(rows, settings, TokenCounter(), [{'role': 'user', 'content': 'x'*24000}]) == []


@pytest.mark.parametrize('method', ['dp', 'greedy'])
@pytest.mark.parametrize('stream', [False, True])
def test_chat_prompt_uses_only_selected_authorized_memories(client, monkeypatch, method, stream):
    login(client); cid = companion(client)
    with client.app.state.db.begin() as db:
        owner = db.scalar(select(User.id))
        for key, text, deleted in [('big', 'x'*400, False), ('short', 'lavender', False),
                                    ('deleted', 'secret', True)]:
            db.add(Memory(id=key, owner=owner, companion=cid, source=key, content=text, deleted=deleted))
    monkeypatch.setattr(Search, 'retrieve', lambda *args: ['deleted', 'big', 'short', 'foreign'])
    settings = client.app.state.settings
    for name, value in [('es_url', 'http://search.invalid'), ('context_selection', method),
                        ('memory_limit', 1), ('memory_token_budget', 20)]:
        object.__setattr__(settings, name, value)
    prompts = []
    class Capture:
        def complete(self, messages):
            prompts.append(messages)
            return Reply('ok', 4)
        def stream(self, messages):
            yield self.complete(messages)
    client.app.state.provider = Capture()
    payload = {'content': 'What do I like?', 'request_id': 'context-select-001'}
    response = client.post(f'/v1/companions/{cid}/messages?stream={str(stream).lower()}', json=payload)
    assert response.status_code == 200
    if stream:
        assert '"type": "done"' in response.text
    assert client.post(f'/v1/companions/{cid}/messages', json=payload).json()['replayed']
    assert len(prompts) == 1
    assert 'MEMORY DATA: ["lavender"]' in prompts[0][0]['content']
    assert 'secret' not in prompts[0][0]['content']
    assert estimate_input(prompts[0]) + settings.max_output <= 24000
    with client.app.state.db() as db:
        assert db.scalar(select(User)).reserved == 0


def test_zero_memory_budget_skips_retrieval_and_paid_preparation(client, monkeypatch):
    login(client); cid = companion(client)
    object.__setattr__(client.app.state.settings, 'es_url', 'http://search.invalid')
    object.__setattr__(client.app.state.settings, 'memory_token_budget', 0)
    calls = []
    def fail(*args):
        calls.append(True)
        raise AssertionError('Retrieval must be disabled')
    monkeypatch.setattr(Search, 'retrieve', fail)
    monkeypatch.setattr('app.main.query_embedding', fail)
    response = client.post(f'/v1/companions/{cid}/messages', json={'content': 'hi', 'request_id': 'no-context-001'})
    assert response.status_code == 200
    assert calls == []


@pytest.mark.parametrize('changes', [{'context_selection': 'unknown'}, {'memory_token_budget': -1}, {'memory_token_budget': 8193}])
def test_invalid_configuration(changes):
    with pytest.raises(RuntimeError):
        replace(Settings(), **changes).validate()
