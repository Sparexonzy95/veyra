import base64
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from django.conf import settings
from rest_framework.exceptions import ValidationError

ISSUE_RE = re.compile(
    r'^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)(?:[/?#].*)?$'
)

STACK_ORDER = {
    'language': 0,
    'runtime': 1,
    'framework': 2,
    'database': 3,
    'testing': 4,
    'styling': 5,
    'infrastructure': 6,
    'package_manager': 7,
}


def parse_issue_url(url: str):
    match = ISSUE_RE.match(url.strip())
    if not match:
        raise ValidationError('Enter a valid public GitHub issue URL.')
    data = match.groupdict()
    data['number'] = int(data['number'])
    return data


def _github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    selected_token = str(token or settings.GITHUB_TOKEN or '').strip()
    if selected_token:
        headers['Authorization'] = f'Bearer {selected_token}'
    return headers


def _clean_version(value: str | None) -> str:
    if not value:
        return ''
    return value.strip().lstrip('^~<>= ').replace('.*', '.x')


def _manifest_text(client: httpx.Client, item: dict[str, Any]) -> str:
    download_url = item.get('download_url')
    if download_url:
        parsed = urlparse(str(download_url))
        if parsed.scheme != 'https' or parsed.hostname not in {
            'raw.githubusercontent.com',
            'github.com',
        }:
            return ''
        response = client.get(download_url, timeout=12, follow_redirects=False)
        if response.is_success:
            return response.text

    url = item.get('url')
    if not url:
        return ''
    response = client.get(url, timeout=12)
    if not response.is_success:
        return ''
    payload = response.json()
    content = payload.get('content')
    if payload.get('encoding') == 'base64' and content:
        try:
            return base64.b64decode(content).decode('utf-8', errors='replace')
        except (ValueError, UnicodeDecodeError):
            return ''
    return ''


def _detect_stack(
    client: httpx.Client,
    owner: str,
    repository: str,
    branch: str,
) -> list[dict[str, str]]:
    endpoint = (
        f"{settings.GITHUB_API_URL.rstrip('/')}/repos/{owner}/{repository}/contents"
        f"?ref={branch}"
    )
    response = client.get(endpoint, timeout=15)
    if not response.is_success:
        return []

    root_items = response.json()
    if not isinstance(root_items, list):
        return []

    by_name = {
        str(item.get('name', '')).lower(): item
        for item in root_items
        if item.get('type') == 'file'
    }
    detected: dict[str, dict[str, str]] = {}

    def add(name: str, category: str, version: str = '', source: str = '') -> None:
        key = name.lower()
        candidate = {
            'name': name,
            'category': category,
            'version': _clean_version(version),
            'source': source,
        }
        existing = detected.get(key)
        if not existing or (not existing.get('version') and candidate['version']):
            detected[key] = candidate

    pyproject_item = by_name.get('pyproject.toml')
    requirements_item = by_name.get('requirements.txt')
    package_item = by_name.get('package.json')

    pyproject = _manifest_text(client, pyproject_item) if pyproject_item else ''
    requirements = _manifest_text(client, requirements_item) if requirements_item else ''

    if pyproject or requirements or 'pipfile' in by_name:
        version_match = re.search(r'requires-python\s*=\s*["\']([^"\']+)', pyproject, re.I)
        add('Python', 'language', version_match.group(1) if version_match else '', 'pyproject.toml' if pyproject else 'requirements.txt')

    python_manifest = f'{pyproject}\n{requirements}'.lower()
    python_packages = [
        ('Django', 'framework', r'\bdjango\s*(?:==|>=|~=|\^)?\s*([\d.]+)?'),
        ('Flask', 'framework', r'\bflask\s*(?:==|>=|~=|\^)?\s*([\d.]+)?'),
        ('FastAPI', 'framework', r'\bfastapi\s*(?:==|>=|~=|\^)?\s*([\d.]+)?'),
        ('Pytest', 'testing', r'\bpytest\s*(?:==|>=|~=|\^)?\s*([\d.]+)?'),
        ('PostgreSQL', 'database', r'\b(?:psycopg|psycopg2|postgres)\b'),
        ('Redis', 'database', r'\bredis\s*(?:==|>=|~=|\^)?\s*([\d.]+)?'),
    ]
    for name, category, pattern in python_packages:
        match = re.search(pattern, python_manifest, re.I)
        if match:
            version = match.group(1) if match.lastindex else ''
            source = 'pyproject.toml' if name.lower() in pyproject.lower() else 'requirements.txt'
            add(name, category, version or '', source)

    if package_item:
        package_text = _manifest_text(client, package_item)
        try:
            package = json.loads(package_text)
        except (json.JSONDecodeError, TypeError):
            package = {}

        dependencies = {
            **(package.get('dependencies') or {}),
            **(package.get('devDependencies') or {}),
        }
        add('Node.js', 'runtime', '', 'package.json')
        if 'typescript' in dependencies or 'tsconfig.json' in by_name:
            add('TypeScript', 'language', dependencies.get('typescript', ''), 'package.json')
        else:
            add('JavaScript', 'language', '', 'package.json')

        js_packages = [
            ('React', 'framework', 'react'),
            ('Next.js', 'framework', 'next'),
            ('Vue', 'framework', 'vue'),
            ('Express', 'framework', 'express'),
            ('Tailwind CSS', 'styling', 'tailwindcss'),
            ('Jest', 'testing', 'jest'),
            ('Vitest', 'testing', 'vitest'),
            ('PostgreSQL', 'database', 'pg'),
            ('Prisma', 'database', 'prisma'),
        ]
        for name, category, package_name in js_packages:
            if package_name in dependencies:
                add(name, category, dependencies[package_name], 'package.json')

        package_manager = str(package.get('packageManager') or '')
        if package_manager:
            manager, _, version = package_manager.partition('@')
            add(manager, 'package_manager', version, 'package.json')
        elif 'pnpm-lock.yaml' in by_name:
            add('pnpm', 'package_manager', '', 'pnpm-lock.yaml')
        elif 'yarn.lock' in by_name:
            add('Yarn', 'package_manager', '', 'yarn.lock')
        elif 'package-lock.json' in by_name:
            add('npm', 'package_manager', '', 'package-lock.json')

    if 'go.mod' in by_name:
        go_mod = _manifest_text(client, by_name['go.mod'])
        version_match = re.search(r'^go\s+([\d.]+)', go_mod, re.M)
        add('Go', 'language', version_match.group(1) if version_match else '', 'go.mod')
    if 'cargo.toml' in by_name:
        add('Rust', 'language', '', 'Cargo.toml')
    if 'pom.xml' in by_name or 'build.gradle' in by_name or 'build.gradle.kts' in by_name:
        add('Java', 'language', '', 'pom.xml' if 'pom.xml' in by_name else 'build.gradle')
    if 'dockerfile' in by_name:
        add('Docker', 'infrastructure', '', 'Dockerfile')
    if 'docker-compose.yml' in by_name or 'docker-compose.yaml' in by_name or 'compose.yml' in by_name:
        add('Docker Compose', 'infrastructure', '', 'docker-compose.yml')

    return sorted(
        detected.values(),
        key=lambda item: (STACK_ORDER.get(item['category'], 99), item['name'].lower()),
    )


def _section_lines(body: str, heading_name: str) -> list[str]:
    lines = body.splitlines()
    collecting = False
    collected: list[str] = []
    target = heading_name.strip().lower()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#'):
            heading = stripped.lstrip('#').strip().lower()
            if collecting:
                break
            collecting = heading == target
            continue
        if collecting:
            collected.append(line)
    return collected


def _extract_acceptance_criteria(body: str) -> list[str]:
    criteria: list[str] = []

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(('- [ ]', '* [ ]')):
            criteria.append(stripped[5:].strip())

    if criteria:
        return criteria

    numbered_criteria: list[str] = []
    bullet_criteria: list[str] = []
    for line in _section_lines(body, 'acceptance criteria'):
        stripped = line.strip()
        numbered = re.match(r'^\d+[.)]\s+(.*)$', stripped)
        bullet = re.match(r'^[-*]\s+(.*)$', stripped)
        if numbered:
            value = numbered.group(1).strip().strip('`')
            if value and not value.endswith(':'):
                numbered_criteria.append(value)
        elif bullet:
            value = bullet.group(1).strip().strip('`')
            if value and not value.endswith(':'):
                bullet_criteria.append(value)

    return numbered_criteria or bullet_criteria


def _extract_suggested_paths(body: str) -> list[str]:
    paths: list[str] = []
    for line in _section_lines(body, 'files likely involved'):
        stripped = line.strip()
        match = re.match(r'^[-*]\s+`?([^`]+)`?$', stripped)
        if match:
            paths.append(match.group(1).strip())
    return paths


def _extract_required_commands(
    body: str,
    stack: list[dict[str, str]],
) -> dict[str, Any]:
    """Detect how the verifier should validate the submitted work.

    CONFIRMED means the command was explicitly written in the GitHub issue.
    SUGGESTED means Veyra inferred a conventional command from the repository stack.
    NEEDS_CONFIRMATION means the client must provide or confirm a command.
    """
    commands: list[str] = []
    in_code_block = False
    for line in _section_lines(body, 'definition of done'):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block and stripped:
            commands.append(stripped)

    if commands:
        return {
            'status': 'CONFIRMED',
            'commands': commands,
            'source': 'GitHub issue — Definition of done',
        }

    names = {item['name'].lower() for item in stack}
    suggestions: list[str] = []
    source = ''

    if 'pytest' in names:
        suggestions = ['pytest']
        source = 'Pytest detected in the repository'
    elif 'django' in names:
        suggestions = ['python manage.py test']
        source = 'Django detected in the repository'
    elif 'jest' in names:
        suggestions = ['npm test']
        source = 'Jest detected in the repository'
    elif 'vitest' in names:
        suggestions = ['npm run test']
        source = 'Vitest detected in the repository'
    elif 'go' in names:
        suggestions = ['go test ./...']
        source = 'Go module detected in the repository'
    elif 'rust' in names:
        suggestions = ['cargo test']
        source = 'Rust project detected in the repository'

    if suggestions:
        return {
            'status': 'SUGGESTED',
            'commands': suggestions,
            'source': source,
        }

    return {
        'status': 'NEEDS_CONFIRMATION',
        'commands': [],
        'source': '',
    }


def fetch_issue(url: str, *, token: str | None = None):
    parsed = parse_issue_url(url)
    headers = _github_headers(token)
    api_root = settings.GITHUB_API_URL.rstrip('/')

    try:
        with httpx.Client(headers=headers, follow_redirects=True) as client:
            issue_response = client.get(
                f"{api_root}/repos/{parsed['owner']}/{parsed['repo']}/issues/{parsed['number']}",
                timeout=15,
            )
            if issue_response.status_code == 404:
                raise ValidationError('GitHub issue was not found or is not public.')
            if issue_response.is_error:
                raise ValidationError('GitHub issue could not be loaded.')

            issue = issue_response.json()
            if 'pull_request' in issue:
                raise ValidationError('The URL points to a pull request, not an issue.')

            repo_response = client.get(
                f"{api_root}/repos/{parsed['owner']}/{parsed['repo']}",
                timeout=15,
            )
            repository = repo_response.json() if repo_response.is_success else {}
            default_branch = repository.get('default_branch', 'main')
            stack = _detect_stack(
                client,
                parsed['owner'],
                parsed['repo'],
                default_branch,
            )
    except httpx.HTTPError as exc:
        raise ValidationError('GitHub could not be reached.') from exc

    body = issue.get('body') or ''
    criteria = _extract_acceptance_criteria(body)
    suggested_paths = _extract_suggested_paths(body)
    validation_detection = _extract_required_commands(body, stack)
    required_commands = validation_detection['commands']

    return {
        'github_issue_url': url,
        'repository_owner': parsed['owner'],
        'repository_name': parsed['repo'],
        'repository_visibility': repository.get('visibility', 'public'),
        'repository_description': repository.get('description') or '',
        'target_branch': default_branch,
        'issue_number': parsed['number'],
        'issue_title': issue.get('title') or '',
        'issue_body': body,
        'issue_state': issue.get('state', 'open'),
        'acceptance_criteria': criteria,
        'repository_stack': stack,
        'suggested_allowed_paths': suggested_paths,
        'suggested_required_commands': required_commands,
        'validation_command_detection': validation_detection,
    }
