# WeChat MCP Desktop

Powered by **Stellaria AXR**. Qt 6 / QML owner application for macOS and Windows.

## Product scope

The first stage covers work and ordinary daily assistance: chat retrieval, document
summaries, meeting and task preparation, and reply drafts. Payments, transfers,
Moments, mini-programs, account changes and group administration are outside scope.
Recommendations do not themselves authorize external actions.

Primary navigation provides the workbench, briefings, tasks, pending approvals and
manual replies. Connection setup, permissions, attachments and execution records
are managed through Settings. Product pages contain no protocol test entry or raw
configuration/diagnostic viewer. Developer checks remain separate from the app UI.
Drag the top area, page title, adjacent header space or brand area to move the
window using the system window manager. Buttons and content keep their normal
interaction behavior.

The app reads actual broker/journal state;
empty or expired results are not replaced with demonstration data. `--fixture`
explicitly labels a synthetic visual preview and never connects to WeChat.

## Run

```sh
python -m pip install -r requirements.desktop.txt
python -m desktop.app --state /private/owner/state --helper /path/to/axr-helper
```

Start the local service from the workbench. Its default is human submission.
Choose a bound conversation in Settings → Permissions to authenticate a 15-minute, 100-use
local read/draft grant. Model disclosure and sends are separately exact-approved.
An explicit recent-day task can be created there. Start a ten-minute **fresh Codex
worker** in Agent connections; review disclosure jobs before approving them.
The worker has no shell, browsing, issuer or send tools and does not copy or submit
messages. No unsolicited model call occurs just because the app starts.

Use the exact-intent dialog to review a pending action, complete OS authentication,
and execute through the broker. The dialog does not turn an arbitrary job into a
grant: the sealed target, body, sources and policy version are rechecked.

The connection page previews a machine-specific `wechat_axr` section, installs it
with `required=false`, and makes a private backup. It checks concurrent changes
before writing and preserves unrelated TOML settings. Restoration refuses to
clobber edits made after installation. Nested/noncanonical sections require manual
review. Its connection test performs actual stdio initialize, tool enumeration and
status; this is not a claim that a model has read messages.

To create a local launcher:

```sh
python scripts/build_desktop.py --state /private/owner/state --helper /path/to/axr-helper
```

macOS gets a local `.app`; Windows gets a `.cmd` launcher (using `pythonw` when
available). These are **development launchers requiring this checkout and Python
runtime**, not relocatable, signed/notarized installers. Distribution packaging,
login items, Windows GUI hardware and long-running operation remain unqualified.
Closing the UI stops its own bounded Codex worker; it does not silently claim to
revoke every independent owner session. Use Revoke all to stop authority.

## Single execution authority

```sh
python -m axr_integration.broker --state /private/owner/state --helper /path/to/axr-helper --listener
python server.py --axr-state /private/owner/state --broker
```

App and MCP clients are observers/requesters. Only the broker activates Service,
owns its journal lease and opens adapters. The existing standalone mode remains
available, but must not be used as a second executor alongside the broker.
Clients can still initialize when the broker is unavailable; business operations
return a safe unavailable error. A required dedicated worker fails closed.

The broker binds only `127.0.0.1`; private current-user-only capability files carry
an ephemeral epoch and separate client/owner tokens. It limits packets to 1 MiB,
connections to 12, validates a fixed method allowlist and never exposes raw SQL,
keys or generic Python dispatch. Requests are serialized with owner changes;
metadata long polls and OS authentication release the control gate. A pending
authentication snapshots the runtime, policy version and intent; revocation or
runtime replacement invalidates it before issuance, so it cannot revive authority. Owner mutation endpoints require
OS authentication, except emergency revocation, which only removes authority.
There is no browser control API, HTTP/CORS endpoint, LAN listener or telemetry.
This is a same-user trusted control surface, **not isolation from an agent with
unrestricted same-user shell/file access**. Tokens are local bearer capabilities,
not an encrypted transport or an external authentication protocol.

## Attachment access

See [Local cached attachments](ATTACHMENTS.md). A cache change is reviewed and
OS-authenticated, revokes prior grants, and reloads the runtime within the same
broker. The UI does not start an independent recovery/execution service.

## Reply submission

`wechat_submit_reply_task` proposes a sealed send from a completed, source-bound
task draft and can execute an exact-approved adapter action without manual copying.
A persisted task/job association and deterministic execution claim prevent repeat
submission. Unknown remains Unknown and is never automatically retried. Sends
still require a qualified backend and exact authority; the default broker rejects
all sends. `--allow-approved-sends` permits approval-based operation only and is
**not permission to send arbitrary messages or evidence of a working backend**.

Current original macOS WeChat still exposes no qualified chat/input identity
path. Real automatic personal-account sending is **not passed**. No blind typing,
client modification, process injection, privacy bypass or substituted bot identity
is used. Synthetic submit/unknown/replay tests are distinguished from hardware.


## Gen1 UI system and validation

Seven pages share Qt Quick color, typography, spacing, radius and line-icon
components. The workbench places connection status, pending tasks and recent
activity ahead of technical diagnostics. Empty states are compact, long labels
wrap/elide, and the 32-pixel status bar has its own layout space. Light/dark themes
share contrast/focus rules; navigation and buttons support Tab, Space and Return.

Real UI state uses the owner's broker projection. Demo mode is explicitly labeled,
never says real WeChat is connected, and disables authority/installation actions.
“Broker connected”, listener request, Agent process running and exact model
permission are distinct. The permission page shows resource-specific access,
model disclosure, expiry, remaining uses and destination; exact intent review shows
human-readable target/body before OS authentication, with technical details separate.

Qt tests render all seven pages in both themes at 1280×800, 1440×900 and
1920×1080; they check footer separation, long bilingual names, empty/loading/error
states and real keyboard activation. 125% and 150% scaling are **render simulations**;
macOS Retina screenshots were inspected separately. These do not substitute for
Windows desktop/device acceptance or screen-reader certification.
