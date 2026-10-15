# SPDX-License-Identifier: MIT
"""Bounded parser subprocess. No files, network calls, macros or shell execution."""
import base64
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from adapters.attachments import extract_text


def main():
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (8, resource.getrlimit(resource.RLIMIT_CPU)[1]))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))
        if sys.platform!='darwin':
            resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,resource.getrlimit(resource.RLIMIT_AS)[1]))
        else:
            # Darwin does not implement RLIMIT_AS/DATA for this interpreter.
            # This is a bounded parser watchdog, not an OS security sandbox.
            import threading,time,os
            def watch():
                while True:
                    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>512*1024**2:os._exit(77)
                    time.sleep(.02)
            threading.Thread(target=watch,daemon=True).start()
    from axr.aet import AXRError
    try:
        data = sys.stdin.buffer.read(800000)
        if len(data) >= 800000:
            raise AXRError('attachment_parser_input_budget')
        request = json.loads(data)
        result = extract_text(base64.b64decode(request['content'], validate=True), request['filename'])
        print(json.dumps(result, ensure_ascii=True))
    except Exception:
        print(json.dumps({'error': 'attachment_parse_failed'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
