# SPDX-License-Identifier: MIT
"""Durable one-attempt marker. It never authorizes or retries a send."""
import json
import os

def claim_attempt(path):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump({'attempted':True,'retry':False},stream);stream.flush();os.fsync(stream.fileno())
    directory=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(directory)
    finally:os.close(directory)
