import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv('DATABASE_URL', 'sqlite:///./near.db')
    origin: str = os.getenv('WEB_ORIGIN', 'http://localhost:3000')
    environment: str = os.getenv('APP_ENV', 'development')
    provider: str = os.getenv('AI_PROVIDER', 'mock')
    qwen_url: str = os.getenv('QWEN_BASE_URL', '')
    qwen_key: str = field(default=os.getenv('QWEN_API_KEY', ''), repr=False)
    chat_model: str = os.getenv('QWEN_CHAT_MODEL', 'qwen-plus')
    embedding_model: str = os.getenv('QWEN_EMBEDDING_MODEL', 'text-embedding-v4')
    embedding_dims: int = int(os.getenv('EMBEDDING_DIMS', '1024'))
    bm25_candidates: int = int(os.getenv('BM25_CANDIDATES', '20'))
    knn_candidates: int = int(os.getenv('KNN_CANDIDATES', '20'))
    knn_num_candidates: int = int(os.getenv('KNN_NUM_CANDIDATES', '100'))
    fusion_candidates: int = int(os.getenv('FUSION_CANDIDATES', '40'))
    memory_limit: int = int(os.getenv('MEMORY_LIMIT', '5'))
    context_selection: str = os.getenv('CONTEXT_SELECTION', 'dp')
    memory_token_budget: int = int(os.getenv('MEMORY_TOKEN_BUDGET', '2048'))
    qwen_tokenizer_path: str = os.getenv('QWEN_TOKENIZER_PATH', '')
    rerank_enabled: bool = os.getenv('RERANK_ENABLED', 'false').lower() == 'true'
    rerank_url: str = os.getenv('RERANK_URL', '')
    rerank_key: str = field(default=os.getenv('RERANK_API_KEY', ''), repr=False)
    rerank_model: str = os.getenv('RERANK_MODEL', 'gte-rerank-v2')
    rerank_candidates: int = int(os.getenv('RERANK_CANDIDATES', '20'))
    rerank_timeout: float = float(os.getenv('RERANK_TIMEOUT_SECONDS', '10'))
    es_url: str = os.getenv('ELASTICSEARCH_URL', '')
    es_key: str = field(default=os.getenv('ELASTICSEARCH_API_KEY', ''), repr=False)
    es_user: str = os.getenv('ELASTICSEARCH_USER', '')
    es_password: str = field(default=os.getenv('ELASTICSEARCH_PASSWORD', ''), repr=False)
    redis_url: str = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    token_limit: int = int(os.getenv('TOKEN_LIMIT', '100000'))
    max_concurrent_requests: int = int(os.getenv('MAX_CONCURRENT_REQUESTS', '32'))
    stream_timeout: float = float(os.getenv('STREAM_TIMEOUT_SECONDS', '120'))
    provider_timeout: float = float(os.getenv('PROVIDER_TIMEOUT_SECONDS', '45'))
    max_output: int = 512
    site_token_limit: int = int(os.getenv('SITE_TOKEN_LIMIT', '1000000'))
    email_mode: str = os.getenv('EMAIL_MODE', 'development')
    smtp_host: str = os.getenv('SMTP_HOST', '')
    smtp_port: int = int(os.getenv('SMTP_PORT', '587'))
    smtp_user: str = os.getenv('SMTP_USER', '')
    smtp_password: str = field(default=os.getenv('SMTP_PASSWORD', ''), repr=False)
    smtp_from: str = os.getenv('SMTP_FROM', '')
    smtp_tls: bool = os.getenv('SMTP_TLS', 'true') == 'true'
    auth_secret: str = field(default=os.getenv('AUTH_SECRET', ''), repr=False)
    auto_schema: bool = os.getenv('AUTO_SCHEMA', 'true') == 'true'
    portrait_api_key: str = field(default='', repr=False)

    def validate(self) -> None:
        import math
        if self.context_selection not in {'dp', 'greedy'} or not 0 <= self.memory_token_budget <= 8192:
            raise RuntimeError('CONTEXT_SELECTION must be dp or greedy; MEMORY_TOKEN_BUDGET must be 0..8192')
        if any(not 1 <= value <= 500 for value in (
            self.bm25_candidates, self.knn_candidates, self.fusion_candidates, self.rerank_candidates
        )) or not self.knn_candidates <= self.knn_num_candidates <= 10000:
            raise RuntimeError('Invalid retrieval candidate limits')
        if not 1 <= self.memory_limit <= 10 or self.memory_limit > self.fusion_candidates:
            raise RuntimeError('MEMORY_LIMIT must be between 1 and 10 and within FUSION_CANDIDATES')
        if self.rerank_candidates > self.fusion_candidates or not math.isfinite(self.rerank_timeout) or self.rerank_timeout <= 0:
            raise RuntimeError('Invalid rerank candidate limit or timeout')
        if self.rerank_enabled:
            endpoint = urlsplit(self.rerank_url)
            if (endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password
                    or endpoint.query or endpoint.fragment or '{' in self.rerank_url or '}' in self.rerank_url
                    or not endpoint.path.endswith('/api/v1/services/rerank/text-rerank/text-rerank')
                    or not self.rerank_model.strip() or not (self.rerank_key or self.qwen_key)):
                raise RuntimeError('Rerank requires a full HTTPS DashScope endpoint, model and server-side key')
        if self.max_concurrent_requests < 1 or any(
            not math.isfinite(value) or value <= 0
            for value in (self.stream_timeout, self.provider_timeout)
        ):
            raise RuntimeError('Concurrency and timeout settings must be finite and positive')
        if self.environment != 'development':
            if self.environment != 'production' or self.provider == 'mock' or self.email_mode != 'smtp':
                raise RuntimeError('Production requires Qwen and real SMTP authentication')
            if self.auto_schema or not self.origin.startswith('https://') or not self.database_url.startswith('postgresql'):
                raise RuntimeError('Production requires migrations, HTTPS and PostgreSQL')
            origin = urlsplit(self.origin)
            if (not origin.hostname or origin.username or origin.password or origin.query
                    or origin.fragment or origin.path not in {'', '/'}):
                raise RuntimeError('WEB_ORIGIN must be an HTTPS origin without a path')
            if self.origin.endswith('/'):
                raise RuntimeError('WEB_ORIGIN must not have a trailing slash')
            if not self.es_url.startswith(('http://', 'https://')):
                raise RuntimeError('Production requires an Elasticsearch endpoint')
            if not self.smtp_tls or len(self.auth_secret) < 32 or not (self.es_key or (self.es_user and self.es_password)):
                raise RuntimeError('Production requires TLS email, AUTH_SECRET and Elasticsearch authentication')
        if self.email_mode not in {'development', 'smtp'}:
            raise RuntimeError('Unknown EMAIL_MODE')
        if self.email_mode == 'smtp' and (not self.smtp_host or not self.smtp_from):
            raise RuntimeError('SMTP host and sender are required')
        if self.provider not in {'mock', 'qwen'}:
            raise RuntimeError('Unknown AI_PROVIDER')
        if self.provider == 'qwen' and (not self.qwen_key or not self.qwen_url.startswith('https://')):
            raise RuntimeError('Qwen requires server-side key and HTTPS endpoint')
