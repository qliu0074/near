"""Run Near locally using .env settings, or run isolated mock HTTP/browser checks."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def build_environment(data, provider=None, test_mode=False, environ=None, env_file=None):
    config = dotenv_values(env_file or ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    env = {key: value for key, value in config.items() if value is not None}
    env.update(os.environ if environ is None else environ)
    selected = 'mock' if test_mode else provider or env.get('AI_PROVIDER', 'mock')
    if selected not in {'mock', 'qwen'}:
        raise ValueError('AI_PROVIDER must be mock or qwen.')
    env.update({'APP_ENV': 'development', 'AI_PROVIDER': selected,
                'EMAIL_MODE': 'development', 'AUTO_SCHEMA': 'false',
                'DATABASE_URL': 'sqlite:///' + (data / 'near.db').as_posix(),
                'ELASTICSEARCH_URL': '', 'WEB_ORIGIN': 'http://localhost:3000',
                'API_INTERNAL_URL': 'http://127.0.0.1:8000', 'PORT': '3000',
                'NEXT_TELEMETRY_DISABLED': '1', 'PYTHONIOENCODING': 'utf-8'})
    if selected == 'qwen':
        if not env.get('QWEN_API_KEY', '').strip():
            raise ValueError('Set QWEN_API_KEY in the local .env file before starting Qwen. Do not share the key in chat.')
        endpoint = env.get('QWEN_BASE_URL', '').strip().rstrip('/')
        url = urlsplit(endpoint)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
                or '{' in endpoint or '}' in endpoint or not url.path.endswith('/compatible-mode/v1')):
            raise ValueError('Set QWEN_BASE_URL to your real HTTPS compatible-mode/v1 endpoint; replace {WorkspaceId} with the Singapore workspace ID.')
        env['QWEN_BASE_URL'] = endpoint
        env['QWEN_API_KEY'] = env['QWEN_API_KEY'].strip()
        env['QWEN_CHAT_MODEL'] = env.get('QWEN_CHAT_MODEL', '').strip() or 'qwen-plus'
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Build the web app before starting')
    parser.add_argument('--smoke', action='store_true', help='Run HTTP checks with a temporary database and exit')
    parser.add_argument('--browser', action='store_true', help='Also run browser checks (requires web Playwright)')
    parser.add_argument('--provider', choices=['mock', 'qwen'], help='Override AI_PROVIDER from .env (tests always use mock)')
    parser.add_argument('--check-config', action='store_true', help='Validate configuration without starting services or calling the model')
    args = parser.parse_args()
    test_mode = args.smoke or args.browser
    if test_mode and args.provider == 'qwen':
        parser.error('Browser and smoke checks use mock only; omit --provider qwen.')
    try:
        env = build_environment(ROOT / '.local', args.provider, test_mode)
    except ValueError as error:
        parser.error(str(error))
    if args.check_config:
        print(f'Configuration valid for {env["AI_PROVIDER"]}. No API request was made.')
        return
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is required; install Node 22 and add it to PATH.')
    next_cli = ROOT / 'web/node_modules/next/dist/bin/next'
    if not next_cli.exists():
        raise RuntimeError('Install web dependencies first: cd web && npm ci')
    # Refuse to test another app or stop a service we did not start.
    for port in (3000, 8000):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as error:
                raise RuntimeError(f'Port {port} is in use. Stop its service before running Near.') from error
    with tempfile.TemporaryDirectory(prefix='near-smoke-') as temporary:
        data = Path(temporary) if args.smoke or args.browser else ROOT / '.local'
        data.mkdir(exist_ok=True)
        env['DATABASE_URL'] = 'sqlite:///' + (data / 'near.db').as_posix()
        if args.build:
            subprocess.run([node, str(next_cli), 'build', '--webpack'], cwd=ROOT / 'web', env=env, check=True)
        if not (ROOT / 'web/.next/standalone/server.js').exists():
            raise RuntimeError('No production build found. Run this command again with --build.')
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'api', env=env, check=True)
        processes = []
        try:
            for command, cwd in [
                ([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], ROOT / 'api'),
                ([sys.executable, '-m', 'app.worker', 'local'], ROOT / 'api'),
                ([node, 'scripts/start.mjs'], ROOT / 'web'),
            ]:
                processes.append(subprocess.Popen(command, cwd=cwd, env=env))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 60
            while True:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError('A local service exited; see its error above.')
                try:
                    with opener.open('http://127.0.0.1:3000/v1/health', timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Services did not become ready within 60 seconds.')
                time.sleep(0.25)
            print(f'Near is ready: http://localhost:3000 ({env["AI_PROVIDER"]} AI, local email codes). Ctrl+C to stop.', flush=True)
            if args.smoke or args.browser:
                subprocess.run([sys.executable, 'tests/http_smoke.py'], cwd=ROOT, env=env, check=True)
                if args.browser:
                    subprocess.run([node, 'tests/browser-smoke.cjs'], cwd=ROOT, env=env, check=True)
                    subprocess.run([node, 'tests/pwa-smoke.cjs'], cwd=ROOT, env=env, check=True)
            else:
                while all(process.poll() is None for process in processes):
                    time.sleep(1)
                raise RuntimeError('A local service stopped unexpectedly.')
        except KeyboardInterrupt:
            print('\nStopping Near.')
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
