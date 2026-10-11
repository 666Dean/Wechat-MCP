// SPDX-License-Identifier: AGPL-3.0-only
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
// Recheck broker-created proof against owner-controlled SQLite metadata.
// Only for trusted helpers reached through private inherited pipes; no issuer key.
int axr_check_commit(const char* store_utf8, const char* proof_json);
// Additionally bind the helper's requested resource, operation and send text.
int axr_check_scoped_commit(const char* store_utf8, const char* proof_json,
                           const char* scope_json);
#ifdef __cplusplus
}
#endif
