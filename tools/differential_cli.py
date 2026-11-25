#!/usr/bin/env python3
"""Record original Windows CLI behavior; verify a native port against it.
Only run binaries and test cases you trust. Exact bytes, no silent normalization.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import platform
import subprocess


def file_hash(path):
    sha=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk)
    return sha.hexdigest()


def run_case(binary,case):
    args=case.get('args',[])
    if not isinstance(args,list) or not all(isinstance(a,str) for a in args):raise ValueError('args must be string array')
    raw=base64.b64decode(case.get('stdin_base64',''),validate=True)
    result=subprocess.run([str(binary.resolve()),*args],input=raw,capture_output=True,
                          timeout=float(case.get('timeout',30)),check=False)
    return {'exit':result.returncode,'stdout_base64':base64.b64encode(result.stdout).decode(),
            'stderr_base64':base64.b64encode(result.stderr).decode()}


def record(binary,cases):
    if not isinstance(cases,list) or not cases:raise ValueError("nonempty case list required")
    return {'format':1,'oracle_sha256':file_hash(binary),'oracle_platform':platform.platform(),
            'cases':[{'case':case,'expected':run_case(binary,case)} for case in cases]}


def verify(binary,manifest):
    if manifest.get('format')!=1 or not manifest.get('cases'):raise ValueError('unknown or empty manifest format')
    mismatches=[]
    for i,row in enumerate(manifest['cases']):
        got=run_case(binary,row['case'])
        diff=[key for key,value in row['expected'].items() if got.get(key)!=value]
        if diff:mismatches.append({'case_index':i,'fields':diff})
    return {'matched':not mismatches,'case_count':len(manifest['cases']), 'mismatches':mismatches,
            'port_sha256':file_hash(binary),'oracle_platform':manifest['oracle_platform']}


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('record');a.add_argument('binary',type=Path);a.add_argument('cases',type=Path);a.add_argument('oracle',type=Path)
    a=sub.add_parser('verify');a.add_argument('binary',type=Path);a.add_argument('oracle',type=Path);a.add_argument('--report',type=Path)
    a=p.parse_args()
    if a.mode=='record':
        data=record(a.binary,json.loads(a.cases.read_text()));a.oracle.parent.mkdir(parents=True,exist_ok=True);a.oracle.write_text(json.dumps(data,indent=2)+'\n');return 0
    data=verify(a.binary,json.loads(a.oracle.read_text()));text=json.dumps(data,indent=2);print(text)
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(text+'\n')
    return 0 if data['matched'] else 1

if __name__=='__main__':raise SystemExit(main())
