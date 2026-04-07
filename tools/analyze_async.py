#!/usr/bin/env python3
import ast
import os
import re
from pathlib import Path

ROOT = Path('.')
EXCLUDE_DIRS = {'.venv', 'venv', '__pycache__', '.git', 'teddy wars'}

py_files = [p for p in ROOT.rglob('*.py') if not any(part in EXCLUDE_DIRS for part in p.parts)]

async_funcs = []

for p in py_files:
    try:
        src = p.read_text(encoding='utf-8')
    except Exception:
        continue
    try:
        tree = ast.parse(src)
    except Exception as e:
        print(f"SKIP parse error {p}: {e}")
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            # detect awaited nodes inside function
            has_await = False
            for n in ast.walk(node):
                if isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
                    has_await = True
                    break
            # record decorators text (if any)
            decorators = [ast.unparse(d) if hasattr(ast, 'unparse') else '<decorator>' for d in node.decorator_list]
            has_decorator = len(node.decorator_list) > 0
            async_funcs.append({
                'file': str(p),
                'name': node.name,
                'lineno': node.lineno,
                'has_await': has_await,
                'decorators': decorators,
                'has_decorator': has_decorator,
            })

# Read all sources for searching callsites
all_src = {str(p): p.read_text(encoding='utf-8') for p in py_files}

candidates = []

for af in async_funcs:
    name = af['name']
    # skip dunder-like
    if name.startswith('_') and name[1:].startswith('_'):
        # still consider but be conservative
        pass
    # find callsites: regex word boundary name (possibly attribute access) followed by (
    sites = []
    pat = re.compile(r'\b' + re.escape(name) + r'\s*\(')
    for fp, src in all_src.items():
        for m in pat.finditer(src):
            # get line
            lineno = src.count('\n', 0, m.start()) + 1
            line = src.splitlines()[lineno-1]
            stripped = line.lstrip()
            # skip decorator lines
            if stripped.startswith('@'):
                continue
            # skip the function definition itself
            if re.match(rf'\s*async\s+def\s+{re.escape(name)}\s*\(', line):
                continue
            sites.append({'file': fp, 'lineno': lineno, 'line': line.rstrip()})
    af['callsites'] = sites
    # find awaited calls
    awaited = []
    for site in sites:
           # match await name( or await self.name( or await module.name( etc
           if re.search(r'await\s+(?:[A-Za-z0-9_\.]+\.)*' + re.escape(name) + r'\s*\(', site['line']):
            awaited.append(site)
    af['awaited_calls'] = awaited
    # find if referenced as callback or registered (callback=NAME or add_command(NAME) or get_command etc)
    registered = False
    for fp, src in all_src.items():
        if re.search(r'callback\s*=\s*' + re.escape(name) + r'\b', src):
            registered = True
            break
        if re.search(r'add_command\s*\(\s*' + re.escape(name) + r'\b', src):
            registered = True
            break
        if re.search(re.escape(name) + r'\s*=\s*app_commands\.Command', src):
            registered = True
            break
    af['registered_as_callback'] = registered

    # decide candidate if no await inside, not registered as callback, not awaited anywhere,
    # and has no decorators (decorated funcs are likely event handlers/commands and must stay async)
    if (not af['has_await'] and not af['registered_as_callback'] and len(af['awaited_calls']) == 0
            and not af.get('has_decorator', False)):
        # avoid methods inside classes: check indentation of the function line
        try:
            src = all_src.get(af['file'], '')
            line = src.splitlines()[af['lineno'] - 1]
            leading = len(line) - len(line.lstrip('\t '))
        except Exception:
            leading = 0
        if leading == 0:
            candidates.append(af)

# Print report
print('Found async functions: %d' % len(async_funcs))
print('Candidate async->sync (no await inside, not registered as callback, not awaited anywhere): %d' % len(candidates))
print()
for c in candidates:
    print(f"{c['file']}:{c['lineno']} -> async def {c['name']}()  decorators={c['decorators']}")
    print('  callsites found:', len(c['callsites']))
    # print up to 5 callsites
    for s in c['callsites'][:5]:
        print(f"    {s['file']}:{s['lineno']}: {s['line']}")
    print()

# Also print async functions that have callsites without await (possible errors)
print('Async functions that are sometimes called without await (mixed or missing awaits):')
for af in async_funcs:
    name = af['name']
    sites = af.get('callsites', [])
    if not sites:
        continue
    awaited = af.get('awaited_calls', [])
    if awaited and len(awaited) < len(sites):
        print(f"{af['file']}:{af['lineno']} async {name} has {len(sites)} callsites, {len(awaited)} awaited")
        for s in sites[:5]:
            print(f"    {s['file']}:{s['lineno']}: {s['line']}")
        print()

# Save JSON for later automation
import json
open('tools/async_analysis.json', 'w', encoding='utf-8').write(json.dumps({'async_funcs': async_funcs, 'candidates': candidates}, indent=2))
print('\nWrote tools/async_analysis.json')
