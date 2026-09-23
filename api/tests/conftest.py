"""Keep test collection and default Settings independent of private provider configuration."""
import os

os.environ.update(AI_PROVIDER='mock', EMAIL_MODE='development', APP_ENV='development', AUTO_SCHEMA='true')
