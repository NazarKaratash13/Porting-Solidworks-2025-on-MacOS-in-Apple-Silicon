"""Opt-in instrumentation: count lifted operations, not timing nor hardware accesses."""
import re

EVENTS = ('guest_load', 'guest_store', 'indirect_dispatch', 'flag_read', 'flag_write')
FLAG = re.compile(r'\bptr %(?:zf|cf|of|sf|signed_less)\b')


def event_for_line(line):
    if not line.startswith('  '): return None
    for i, name in enumerate(('guest_load', 'guest_store', 'guest_indirect_dispatch')):
        if re.search(r'\bcall\b[^\n]*@'+name+r'(?:_fast)?\(', line): return i
    if FLAG.search(line):
        if re.search(r'\bload i1\b', line): return 3
        if re.search(r'\bstore i1\b', line): return 4
    return None
