# Local cached chat attachments

The integration resolves files already stored in an owner-selected local cache.
It neither downloads remote URLs nor writes to WeChat's databases.

1. `wechat_find_attachments` reads up to six file records from an authorized
   conversation/time range. WCDB compound message kinds are normalized at the
   low 16 bits; appmsg XML must independently declare file subtype 6. Sender and
   conversation checks remain mandatory. Metadata stays in an encrypted context.
2. The usual exact disclosure operation can show that context to the owner-pinned
   model. URLs, attachment encryption keys and arbitrary local paths are excluded.
3. `wechat_read_attachment(conversation_id, context_id, reference)` requires a
   separate `files.read` capability and a matching unexpired source context.
   Canonical cache roots, regular files, size and message MD5 are checked. The
   original handle/path identity is rechecked around reading; a SHA-256 digest
   identifies the actual bytes. Byte-distinct ambiguous matches are refused.
4. A bounded trusted parser returns a new encrypted text context. Model disclosure
   is still a separate exact action. Sources retain the original account,
   conversation, reference, classification and external-data taint.

## Supported first stage

| Format | Local processing |
| --- | --- |
| TXT, Markdown, CSV, JSON | Strict UTF-8 text, capped output |
| Word `.docx` | Bounded document XML; no macros, links or embedded files executed |
| PDF | Text extraction, at most 50 pages; encrypted PDFs refused |
| Other/media/executables | Explicitly unsupported; never executed |

The initial file limit is **512 KiB**, extracted text at most **24 KB**, 256 ZIP
entries, 8 MiB total expanded archive and a 100:1 expansion ratio. Cache search is
limited to 4096 entries, 32 MiB inspected bytes and five seconds. Large caches
should be scoped to the relevant directory. Search stops rather than claiming
that an incomplete scan proves a file is missing. There is no complete attachment
index, first-stage pagination UI, OCR for scanned PDFs or audio/video transcription.

The message MD5 is a compatibility anchor, not collision-proof authentication.
The actual content is external untrusted data; document instructions never become
issuer authority. Symlinks and pathname/handle changes are refused, but a hostile
same-user filesystem racer still requires OS sandbox containment. No global file
scanner or user-home search is used.

Parsers run as fixed trusted subprocesses through AXR Supervisor: bounded pipes,
10-second timeout, Windows JobObject memory/process limits. POSIX CPU limits are
set; Darwin uses a resident-memory watchdog because its interpreter does not
support the attempted address-space limit. This is **not a fully qualified hostile
file sandbox**. PDFs/DOCX should remain owner-approved, bounded inputs; a hardened
parser sandbox and broader encrypted/media formats remain future work.

## Configuration

Only the local owner configures paths; MCP accepts source references, not paths.

```json
{"attachments": {"enabled": true, "cache_roots": ["/private/wechat/cache/files"]}}
```

Use the Desktop attachment page to select the actual cache folder and complete
OS authentication. Existing read permissions do not automatically grant file
content access. The native SDK contains only generic `files.read` risk semantics;
all WeChat types, paths, XML and parsers stay outside `AXR/`.

## Evidence

2026-10-12: real stdio MCP checked 64 bound conversations, found 55 file records
and parsed one real cached file. Thirty-four attempted queries/contents were
unavailable or unsupported; this count is not a distinct-file denominator. No
model disclosure, send, screenshot, plaintext file export or new login occurred.
The acceptance session revoked authority and restored prior policy on exit.
Public tests cover source/hash matching, XML entities/path injection, archive
expansion, symlink escape, format/output limits, separate file grants, exact
model disclosure, credential masking and revocation. Hardware details stay local.
