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
// Security v2: connect to the fixed protected authority installation, authenticate
// its actual OS peer and bind this helper's process birth and exact action.
// Caller-selected public keys, root executable paths and issuer keys are absent.
int axr_authority_preflight(const char* endpoint_utf8,const char* proof_json,const char* scope_json);
int axr_authority_claim(const char* endpoint_utf8,const char* proof_json,const char* scope_json);
int axr_authority_observe(const char* endpoint_utf8,const char* proof_json,int verified,const char* evidence_digest);
#ifdef __cplusplus
}
#endif
