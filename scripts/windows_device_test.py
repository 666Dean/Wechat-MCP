# SPDX-License-Identifier: MIT
"""Explicit Windows device-test API: metadata inspection or signed qualification."""
import argparse,json,re,sys
from pathlib import Path
from desktop.windows_device_test import inspect_device


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    inspect=commands.add_parser('inspect');inspect.add_argument('--package');inspect.add_argument('--wechat-sha256')
    qualify=commands.add_parser('qualify');qualify.add_argument('--permit',required=True)
    for command in (inspect,qualify):command.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    if sys.stdout is None and args.output is None:parser.error('--output is required without a console')
    try:
        if args.output is not None and args.output.exists():raise ValueError('device_test_output_already_exists')
        if args.command=='inspect':value=inspect_device(package=args.package,wechat_sha256=args.wechat_sha256)
        else:
            from axr_applications.windows_navigation import read_json
            from desktop.windows_lifecycle import qualify_once
            value=qualify_once(read_json(args.permit,20000))
        if args.output is not None:
            with args.output.open('x',encoding='utf-8') as target:target.write(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n')
    except Exception as error:
        code=str(error)
        if re.fullmatch('[a-z][a-z0-9_]{0,99}',code) is None:code='windows_device_test_failed'
        value={'state':'Failed','error':code,'retry':False,'runtime_qualified':False,'authorization_granted':False}
    if sys.stdout is not None:print(json.dumps(value,ensure_ascii=False,sort_keys=True))
    return 0 if value.get('state') in ('PrerequisitesObserved','Recorded') else 2


if __name__=='__main__':raise SystemExit(main())
