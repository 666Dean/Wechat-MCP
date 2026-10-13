# Integration notices

The code outside AXR/ retains MIT, subject to original third-party notices.
AXR/ is separately AGPL-3.0-only. Combining or distributing a program that links
AXR may impose AGPL obligations on the combined program; an MIT header does not
remove those obligations. See AXR/THIRD_PARTY_NOTICES.md for SDK dependencies.

## Optional SQLite3 Multiple Ciphers reader

`requirements.sqlite3mc.txt` selects [apsw-sqlite3mc](https://github.com/utelle/apsw-sqlite3mc)
3.53.4.0, combining [APSW](https://github.com/rogerbinns/apsw) and
[SQLite3 Multiple Ciphers](https://github.com/utelle/SQLite3MultipleCiphers).
The integration independently uses their public APIs; no upstream source or
wheel is vendored here. Dependencies and their bundled cryptographic components
retain their own license notices, including the wheel's original LICENSE file.
Distributions must preserve those notices; the integration's MIT header does
not relicense dependency code. The verified wheel identifies its APSW license
as `any-OSI`, with the original terms retained in the installed distribution.

## WeChat AX layout utilities

adapters/macos/layout.py adapts selected identifiers and title normalization
from [dustin573/wechat-mcp](https://github.com/dustin573/wechat-mcp), revision
c6c600ae068c113224f984656db40f8cec4d0164. Display-name session identifiers
are not treated as stable account/conversation IDs. Its global key-event send
implementation is not included.

MIT License

Copyright (c) 2025 Banghao Chi
Copyright (c) 2026 Dustin Chan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Other dependencies

MCP Python SDK: MIT. zstandard: BSD. wxauto4 and its dependencies retain their
upstream licensing; used only by the legacy Windows path. No WCDB decryption
binary, private keys, messages, or third-party executable is bundled here.
Tencent WCDB and SQLCipher were consulted as codec/API references; the integration
uses an owner-provided SQLCipher library rather than copying their source.
The huj28-creator/wechat-fastbridge tree was reviewed for accessibility compatibility;
no implementation was copied from it.

## Bounded WCDB sender and text decoding references

`adapters/wcdb.py` adapts the Name2Id rowid-to-username mapping and Zstandard
magic detection from labazhou2024/chatlog-keeper, revision
2225294fd0761e10ce15540f21e7dbb2ac304c3c. Per-page bounded lookups replace
loading the full name map. Decode errors reject rather than silently replacing text.
Native SQLCipher pager replaces its plaintext full-database snapshot exporter.

MIT License

Copyright (c) 2026 labazhou2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## WCDB first-page key validation

`adapters/wcdb_keys.py` adapts the selected SQLCipher4 first-page HMAC rule from
[acmerfight's local toolkit](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f),
version c98dbb10cf23c30e83d5d744905101b0880887a0. Its plaintext key-file export,
LLDB capture, full database reader and send implementation are not included.
The startup observer forwards CommonCrypto unchanged and has an independent
synthetic fixture; no private WeChat executable is distributed.

MIT License

Copyright (c) 2026 Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


## Desktop and bounded attachment dependencies

- PySide6-Essentials / Shiboken 6.10.2: LGPL-3.0-only OR GPL-2.0-only OR
  GPL-3.0-only, with Qt modules under their respective licenses. This repository
  does not relicense Qt or distribute a commercial Qt entitlement.
  [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html).
- defusedxml 0.7.1: Python Software Foundation License.
  [Project license](https://github.com/tiran/defusedxml/blob/main/LICENSE).
- pypdf 6.6.0: BSD-3-Clause.
  [Project license](https://github.com/py-pdf/pypdf/blob/main/LICENSE).

The WCDB compound-kind normalization was independently implemented after
reviewing the MIT chatlog-keeper reader already attributed above. No third-party
sending installer, binary hook, privacy bypass or private framework is included.
