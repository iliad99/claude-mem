#!/usr/bin/env python3
"""SessionStart(resume): give the claude-mem timeline once to a conversation that never got one.

Upstream skips resume on purpose (#4423): a restored conversation already holds its
timeline, and a fresh one would change its prompt. But a conversation started before
claude-mem was installed, then restarted with --resume, never gets one at all.
If the live part of the transcript (after the last compaction) already holds a
claude-mem SessionStart context, do nothing; otherwise run the normal context hook
as a startup.
"""
import json
import subprocess
import sys

MARKS = ('# claude-mem memory use', '] recent context, ')


def injected(transcript_path):
    found = False
    try:
        f = open(transcript_path, encoding='utf-8', errors='replace')
    except OSError:
        return True  # can't tell: keep upstream behaviour
    with f:
        for line in f:
            if '"compact_boundary"' not in line and (found or '"hook_additional_context"' not in line):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get('type') == 'system' and d.get('subtype') == 'compact_boundary':
                found = False
                continue
            a = d.get('attachment') or {}
            if a.get('type') == 'hook_additional_context' and a.get('hookEvent') == 'SessionStart':
                found = found or any(m in c for c in a.get('content') or [] if isinstance(c, str) for m in MARKS)
    return found


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    if data.get('source') != 'resume' or injected(data.get('transcript_path') or ''):
        return 0
    data['source'] = 'startup'
    try:
        return subprocess.run(['claude-mem', 'hook', 'claude-code', 'context'], input=json.dumps(data), text=True, timeout=50).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 0  # no launcher or too slow: same as upstream (no timeline)


def selftest():
    import os
    import tempfile
    ctx = lambda text: json.dumps({'type': 'attachment', 'attachment': {'type': 'hook_additional_context', 'hookEvent': 'SessionStart', 'content': [text]}})
    boundary = '{"type":"system","subtype":"compact_boundary"}'
    cases = [
        ([], False),
        ([ctx('<context_window_protection>')], False),
        ([ctx('# [Architector] recent context, 2026-11-02')], True),
        ([ctx('# claude-mem memory use\n...')], True),
        ([ctx('# [A] recent context, x'), boundary], False),
        ([ctx('# [A] recent context, x'), boundary, ctx('# [A] recent context, y')], True),
        (['{"type":"user","message":{"content":"# claude-mem memory use 를 인용"}}'], False),
        ([ctx('# [A] recent context, x'), '{"type":"user","message":{"content":"\\"compact_boundary\\" 를 인용"}}'], True),
        ([ctx('# [A] recent context, x')[:40], ctx('# [A] recent context, y')], True),
    ]
    for lines, want in cases:
        with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
            f.write('\n'.join(lines) + '\n')
        assert injected(f.name) is want, (lines, want)
        os.unlink(f.name)
    assert injected('/nonexistent/x.jsonl') is True
    print('selftest ok', len(cases) + 1)


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    else:
        sys.exit(main())
