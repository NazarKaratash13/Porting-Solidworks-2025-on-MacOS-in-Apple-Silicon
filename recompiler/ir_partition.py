"""Streaming partitioner for ConsoleLift's *generated* text dialect, not arbitrary IR.

Two sequential passes, no LLVM parser of the whole module. Function bodies are
spooled directly to separate files. Global identity is preserved in shard 0;
internal symbols crossing shards are promoted to hidden linkage. Fast memory
helpers are copied with internal linkage to preserve local inlining.
Unknown top-level forms fail closed rather than guessing their semantics.
"""
from pathlib import Path
from contextlib import ExitStack
import re

SYMBOL = r'[-A-Za-z$._0-9]+'
REF = re.compile(r'@(' + SYMBOL + r')')
FUNC = re.compile(r'^define (?:(internal) )?(void|i\d+) @(' + SYMBOL + r')\(([^()]*)\) (.*?)\{\s*$')
GLOBAL = re.compile(r'^@(' + SYMBOL + r') = (?:(external|internal|private) )?(?:(unnamed_addr) )?(global|constant) (.*)$')
HELPERS = {'guest_load_fast', 'guest_store_fast', 'guest_check_return_fast'}


def global_type(value):
    if value.startswith('['):
        depth = 0
        for i, char in enumerate(value):
            if char == '[': depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0: return value[:i+1]
    else:
        match = re.match(r'i\d+\b', value)
        if match: return match.group()
    raise ValueError('unsupported generated global type')


def function_declaration(match):
    internal, result, name, args, attributes = match.groups()
    # ConsoleLift uses only simple ptr/integer arguments for defined functions.
    types = []
    for arg in args.split(',') if args else []:
        m = re.fullmatch(r'\s*(ptr|i\d+) %[-\w.]+\s*', arg)
        if not m: raise ValueError(f'unsupported generated parameter: {arg}')
        types.append(m[1])
    if attributes.strip(): raise ValueError(f'unsupported function attributes: {attributes}')
    return f'declare {"hidden " if internal else ""}{result} @{name}({", ".join(types)})\n'


def partition_generated_ir(source, work: Path, parts: int) -> list[Path]:
    """Accept a Path or a stream of transformed IR lines from the lifter."""
    if not 2 <= parts <= 256: raise ValueError('parts must be 2..256')
    work.mkdir(parents=True, exist_ok=True)
    # Definitions / declarations are indexed by name, not by whole body text.
    definitions = {}
    declarations = {}
    refs = [set() for _ in range(parts)]
    owners = [set() for _ in range(parts)]
    paths = [work / f'body{i}.tmp' for i in range(parts)]
    globals_path = work / 'globals.tmp'
    helpers_path = work / 'helpers.tmp'
    metadata_path = work / 'metadata.tmp'
    current = None
    ordinal = 0
    with ExitStack() as stack:
        bodies = [stack.enter_context(p.open('w', encoding='utf-8')) for p in paths]
        globals_out = stack.enter_context(globals_path.open('w', encoding='utf-8'))
        helpers_out = stack.enter_context(helpers_path.open('w', encoding='utf-8'))
        meta_out = stack.enter_context(metadata_path.open('w', encoding='utf-8'))
        stream = stack.enter_context(source.open(encoding='utf-8')) if isinstance(source, Path) else source
        for line in stream:
            if current is not None:
                out, index = current
                out.write(line)
                if index is not None: refs[index].update(m[1] for m in REF.finditer(line))
                if line.strip() == '}': current = None
                continue
            if not line.strip() or line.startswith(';'): continue
            if line.startswith('define '):
                m = FUNC.fullmatch(line.rstrip('\n'))
                if not m: raise ValueError(f'unsupported generated function header: {line[:100]}')
                internal, _, name, _, _ = m.groups()
                if name in HELPERS:
                    if not internal: raise ValueError('fast helper must be internal')
                    helpers_out.write(line)
                    current = (helpers_out, None)
                    continue
                if name in definitions: raise ValueError(f'duplicate definition: {name}')
                index = ordinal % parts
                ordinal += 1
                definitions[name] = function_declaration(m)
                owners[index].add(name)
                bodies[index].write(line.replace('define internal ', 'define hidden ', 1) if internal else line)
                current = (bodies[index], index)
            elif line.startswith('declare '):
                match = REF.search(line)
                if not match: raise ValueError('invalid declaration')
                name = match[1]
                if name in declarations and declarations[name] != line: raise ValueError(f'conflicting declaration {name}')
                declarations[name] = line
            elif line.startswith('@'):
                m = GLOBAL.fullmatch(line.rstrip('\n'))
                if not m: raise ValueError(f'unsupported generated global: {line[:100]}')
                name, linkage, unnamed, kind, value = m.groups()
                ty = global_type(value)
                if linkage == 'external':
                    declarations[name] = line
                    continue
                if name in definitions: raise ValueError(f'duplicate definition: {name}')
                local = linkage in ('private', 'internal')
                definitions[name] = f'@{name} = external {"hidden " if local else ""}{kind} {ty}\n'
                owners[0].add(name)
                refs[0].update(m[1] for m in REF.finditer(line))
                if local:
                    # unnamed_addr intentionally preserved on the definition.
                    line = line.replace(f'= {linkage} ', '= hidden ', 1)
                globals_out.write(line)
            elif line.startswith('!'):
                meta_out.write(line)
            else:
                raise ValueError(f'unsupported generated top-level IR: {line[:100]}')
    if current is not None: raise ValueError('unterminated generated function')
    if not ordinal: raise ValueError('no generated functions')
    import shutil
    result = []
    for i, body in enumerate(paths):
        target = work / f'direct{i}.ll'
        with target.open('w', encoding='utf-8') as out:
            for line in declarations.values(): out.write(line)
            for name in sorted(refs[i] - owners[i]):
                if name in definitions: out.write(definitions[name])
            for p in ([globals_path] if i == 0 else []) + [body, helpers_path, metadata_path]:
                with p.open(encoding='utf-8') as stream: shutil.copyfileobj(stream, out, length=1024*1024)
        result.append(target)
    for p in [*paths, globals_path, helpers_path, metadata_path]: p.unlink()
    return result
