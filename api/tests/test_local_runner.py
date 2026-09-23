import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('near_local_runner', Path(__file__).resolve().parents[2] / 'scripts/run-local.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_real_provider_reads_private_env_without_forcing_mock(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('AI_PROVIDER=qwen\nQWEN_API_KEY=test-only\nQWEN_BASE_URL=https://example.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1\nQWEN_CHAT_MODEL=qwen-plus\n')
    env = runner.build_environment(tmp_path, environ={}, env_file=env_file)
    assert env['AI_PROVIDER'] == 'qwen'
    assert env['QWEN_API_KEY'] == 'test-only'
    assert env['QWEN_CHAT_MODEL'] == 'qwen-plus'
    assert env['EMAIL_MODE'] == 'development'
    assert env['ELASTICSEARCH_URL'] == ''


def test_tests_and_explicit_demo_do_not_require_or_use_real_provider(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('AI_PROVIDER=qwen\nQWEN_API_KEY=\n')
    assert runner.build_environment(tmp_path, test_mode=True, environ={}, env_file=env_file)['AI_PROVIDER'] == 'mock'
    assert runner.build_environment(tmp_path, provider='mock', environ={}, env_file=env_file)['AI_PROVIDER'] == 'mock'


def test_real_provider_requires_key_and_resolved_endpoint(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('AI_PROVIDER=qwen\n')
    with pytest.raises(ValueError, match='QWEN_API_KEY'):
        runner.build_environment(tmp_path, environ={}, env_file=env_file)
    with pytest.raises(ValueError, match='WorkspaceId'):
        runner.build_environment(tmp_path, environ={'QWEN_API_KEY': 'test-only',
            'QWEN_BASE_URL': 'https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1'}, env_file=env_file)


def test_environment_and_explicit_override_take_precedence(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('AI_PROVIDER=qwen\n')
    assert runner.build_environment(tmp_path, environ={'AI_PROVIDER': 'mock'}, env_file=env_file)['AI_PROVIDER'] == 'mock'
    assert runner.build_environment(tmp_path, provider='mock', environ={}, env_file=env_file)['AI_PROVIDER'] == 'mock'
