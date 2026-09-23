from collections import defaultdict
import httpx
from .config import Settings


def rrf(*rankings: list[str], limit: int = 5) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(dict.fromkeys(ranking), start=1):
            scores[item] += 1 / (60 + rank)
    return sorted(scores, key=lambda item: (-scores[item], item))[:limit]


class Search:
    def __init__(self, settings: Settings):
        self.settings = settings

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {'Authorization': f'ApiKey {self.settings.es_key}'} if self.settings.es_key else {}
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            response = client.request(method, self.settings.es_url.rstrip('/') + path,
                                      headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    def create_index(self) -> None:
        properties = {
            'owner': {'type': 'keyword'}, 'companion': {'type': 'keyword'},
            'content': {'type': 'text', 'analyzer': 'cjk'},
            'deleted': {'type': 'boolean'}, 'version': {'type': 'long'},
            'embedding_model': {'type': 'keyword'},
            'embedding': {'type': 'dense_vector', 'dims': self.settings.embedding_dims,
                          'index': True, 'similarity': 'cosine'}}
        try:
            self.request('PUT', '/near-memories-v1', {'mappings': {'properties': properties}})
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 400 or error.response.json().get('error', {}).get('type') != 'resource_already_exists_exception':
                raise
            # Adding new keyword fields is safe; incompatible vector dimensions must fail startup.
            self.request('PUT', '/near-memories-v1/_mapping', {'properties': properties})

    def retrieve(self, owner: str, companion: str, query: str, vector: list[float] | None) -> list[str]:
        filters = [{'term': {'owner': owner}}, {'term': {'companion': companion}},
                   {'term': {'deleted': False}}]
        lexical = self.request('POST', '/near-memories-v1/_search', {
            'size': 20, '_source': False,
            'query': {'bool': {'filter': filters, 'must': [{'match': {'content': query}}]}}})
        first = [hit['_id'] for hit in lexical['hits']['hits']]
        if vector is None:
            return first[:5]
        try:
            semantic = self.request('POST', '/near-memories-v1/_search', {
                'size': 20, '_source': False, 'knn': {'field': 'embedding', 'query_vector': vector,
                'k': 20, 'num_candidates': 100, 'filter': {'bool': {'filter': filters + [
                    {'term': {'embedding_model': self.settings.embedding_model}}]}}}})
        except httpx.HTTPError:
            return first[:5]
        return rrf(first, [hit['_id'] for hit in semantic['hits']['hits']])

    def index(self, memory_id: str, document: dict, version: int) -> None:
        try:
            self.request('PUT', f'/near-memories-v1/_doc/{memory_id}?version={version}&version_type=external_gte', document)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 409:
                raise
            # A later source version has already won; never resurrect an older record.
