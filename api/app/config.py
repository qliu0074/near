import os
from dataclasses import dataclass, field
from pathlib import Path
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
    es_url: str = os.getenv('ELASTICSEARCH_URL', '')
    es_key: str = field(default=os.getenv('ELASTICSEARCH_API_KEY', ''), repr=False)
    redis_url: str = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    token_limit: int = int(os.getenv('TOKEN_LIMIT', '100000'))
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
        if self.environment != 'development':
            if self.environment != 'production' or self.provider == 'mock' or self.email_mode != 'smtp':
                raise RuntimeError('Production requires Qwen and real SMTP authentication')
            if self.auto_schema or not self.origin.startswith('https://') or not self.database_url.startswith('postgresql'):
                raise RuntimeError('Production requires migrations, HTTPS and PostgreSQL')
            if not self.smtp_tls or len(self.auth_secret) < 32 or not self.es_key:
                raise RuntimeError('Production requires TLS email, AUTH_SECRET and Elasticsearch authentication')
        if self.email_mode not in {'development', 'smtp'}:
            raise RuntimeError('Unknown EMAIL_MODE')
        if self.email_mode == 'smtp' and (not self.smtp_host or not self.smtp_from):
            raise RuntimeError('SMTP host and sender are required')
        if self.provider not in {'mock', 'qwen'}:
            raise RuntimeError('Unknown AI_PROVIDER')
        if self.provider == 'qwen' and (not self.qwen_key or not self.qwen_url.startswith('https://')):
            raise RuntimeError('Qwen requires server-side key and HTTPS endpoint')
