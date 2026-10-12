# SPDX-License-Identifier: MIT
"""Read-only SQLCipher/WCDB C API. Explicit libraries, keys, schema and conversations.

No process scanning, export-all, DLL injection, raw SQL tool, or plaintext cache.
Selected text/Name2Id rules adapted from MIT chatlog-keeper; see THIRD_PARTY_NOTICES.md.
SQLCipher's pager handles HMAC checks, transactions and committed WAL visibility.
"""
import ctypes as C
import hashlib
import json
import re
import time
import threading
from pathlib import Path
from axr.aet import AXRError, canonical, digest


class CipherConnection:
    def __init__(self, path, library, key, profile):
        if not Path(library).is_absolute() or not Path(library).is_file():
            raise AXRError("sqlcipher_library_not_configured")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
            raise AXRError("invalid_database_key")
        self.lib = C.CDLL(str(library))
        self.handle = C.c_void_p()
        self._declare()
        uri = Path(path).resolve(strict=True).as_uri()+"?mode=ro"
        if self.lib.sqlite3_open_v2(uri.encode(), C.byref(self.handle), 1|0x40|0x10000|0x01000000, None) != 0:
            self.close()
            raise AXRError("database_readonly_open_failed")
        try:
            self.query("PRAGMA key=\"x'"+key+"'\"")
            # Explicit owner-verified SQLCipher codec profile; never guess on live files.
            if profile not in {"sqlcipher4", "wcdb4-raw", "sqlcipher3"}:
                raise AXRError("unsupported_cipher_profile")
            if profile == "sqlcipher3":
                self.query("PRAGMA cipher_compatibility=3")
            elif profile == "wcdb4-raw":
                self.query("PRAGMA cipher_page_size=4096")
                self.query("PRAGMA cipher_hmac_algorithm=HMAC_SHA512")
                self.query("PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_SHA512")
                self.query("PRAGMA cipher_use_hmac=ON")
            if not self.query("PRAGMA cipher_version"):
                raise AXRError("library_is_not_sqlcipher")
            self.query("PRAGMA query_only=ON")
            self.query("PRAGMA trusted_schema=OFF")
            self.query("SELECT count(*) FROM sqlite_master")
        except BaseException:
            self.close()
            raise

    def _declare(self):
        self.life_lock=threading.RLock()
        definitions = {
            "sqlite3_open_v2": ([C.c_char_p,C.POINTER(C.c_void_p),C.c_int,C.c_char_p],C.c_int),
            "sqlite3_busy_timeout": ([C.c_void_p,C.c_int],C.c_int),
            "sqlite3_interrupt": ([C.c_void_p],None),
            "sqlite3_close_v2": ([C.c_void_p],C.c_int),
            "sqlite3_prepare_v2": ([C.c_void_p,C.c_char_p,C.c_int,C.POINTER(C.c_void_p),C.c_void_p],C.c_int),
            "sqlite3_step": ([C.c_void_p],C.c_int),
            "sqlite3_finalize": ([C.c_void_p],C.c_int),
            "sqlite3_bind_text": ([C.c_void_p,C.c_int,C.c_char_p,C.c_int,C.c_void_p],C.c_int),
            "sqlite3_bind_int64": ([C.c_void_p,C.c_int,C.c_int64],C.c_int),
            "sqlite3_column_count": ([C.c_void_p],C.c_int),
            "sqlite3_column_name": ([C.c_void_p,C.c_int],C.c_char_p),
            "sqlite3_column_type": ([C.c_void_p,C.c_int],C.c_int),
            "sqlite3_column_int64": ([C.c_void_p,C.c_int],C.c_int64),
            "sqlite3_column_blob": ([C.c_void_p,C.c_int],C.c_void_p),
            "sqlite3_column_bytes": ([C.c_void_p,C.c_int],C.c_int),
        }
        for name,(args,result) in definitions.items():
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=result

    def query(self, sql, parameters=()):
        stmt=C.c_void_p()
        if self.lib.sqlite3_prepare_v2(self.handle,sql.encode(),-1,C.byref(stmt),None)!=0:
            raise AXRError("database_key_profile_schema_or_query_failed")
        # Enforce a wall/VM-step ceiling even when the owner's table lacks an index.
        progress_type=C.CFUNCTYPE(C.c_int,C.c_void_p)
        self.lib.sqlite3_progress_handler.argtypes=[C.c_void_p,C.c_int,progress_type,C.c_void_p]
        self.lib.sqlite3_progress_handler.restype=None
        deadline=time.monotonic()+5
        progress=progress_type(lambda _:int(time.monotonic()>deadline))
        self.lib.sqlite3_progress_handler(self.handle,1000,progress,None)
        storage=[]
        try:
            for i,value in enumerate(parameters,1):
                if type(value) is int:
                    code=self.lib.sqlite3_bind_int64(stmt,i,value)
                else:
                    encoded=str(value).encode();storage.append(encoded)
                    code=self.lib.sqlite3_bind_text(stmt,i,encoded,len(encoded),None)
                if code!=0:
                    raise AXRError("database_parameter_failed")
            rows=[]
            while True:
                code=self.lib.sqlite3_step(stmt)
                if code==101:
                    return rows
                if code!=100:
                    raise AXRError("database_query_failed_not_empty_result")
                if len(rows)>=1001:
                    raise AXRError("database_result_budget_exceeded")
                row={}
                for i in range(self.lib.sqlite3_column_count(stmt)):
                    name=self.lib.sqlite3_column_name(stmt,i).decode()
                    kind=self.lib.sqlite3_column_type(stmt,i)
                    if kind==1:
                        value=self.lib.sqlite3_column_int64(stmt,i)
                    elif kind==5:
                        value=None
                    else:
                        size=self.lib.sqlite3_column_bytes(stmt,i)
                        if size>1024*1024:
                            raise AXRError("database_cell_budget_exceeded")
                        value=C.string_at(self.lib.sqlite3_column_blob(stmt,i),size)
                        if kind==3:
                            value=value.decode("utf-8",errors="strict")
                    row[name]=value
                rows.append(row)
        finally:
            self.lib.sqlite3_progress_handler(self.handle,0,progress_type(),None)
            self.lib.sqlite3_finalize(stmt)

    def interrupt(self):
        with self.life_lock:
            if self.handle and self.handle.value:self.lib.sqlite3_interrupt(self.handle)

    def close(self):
        with self.life_lock:
            if self.handle and self.handle.value:
                self.lib.sqlite3_close_v2(self.handle)
                self.handle=C.c_void_p()


def decode_text(value, compression):
    # WCDB CompressionConst.hpp encodes compressed-kind << 1 | original-blob.
    # 4/5 are ordinary Zstd; 2/3 require a separately qualified dictionary.
    if type(compression) is not int or compression not in (0,1,2,3,4,5):
        raise AXRError("unknown_wcdb_compression")
    if compression in (2,3):raise AXRError("wcdb_compression_dictionary_required")
    if isinstance(value,str) and compression==0:
        if len(value.encode('utf8'))>1024*1024:raise AXRError('message_body_budget_exceeded')
        return value
    if isinstance(value,bytes):
        if len(value)>1024*1024:raise AXRError('message_body_budget_exceeded')
        if compression in (0,1) and not value.startswith(b"\x28\xb5\x2f\xfd"):
            return value.decode("utf-8",errors="strict")
        import zstandard
        try:
            params=zstandard.get_frame_parameters(value)
            if params.dict_id:raise AXRError('wcdb_compression_dictionary_required')
            if params.content_size not in (zstandard.CONTENTSIZE_UNKNOWN,zstandard.CONTENTSIZE_ERROR) and params.content_size>1024*1024:
                raise AXRError('message_body_budget_exceeded')
            # Known sizes were capped above; unknown sizes use a capped buffer.
            # Require one complete frame: streaming reads can accept truncation.
            decoded=zstandard.ZstdDecompressor(max_window_size=1024).decompress(
                value,max_output_size=1024*1024,allow_extra_data=False)
            return decoded.decode('utf8',errors='strict')
        except zstandard.ZstdError as exc:raise AXRError('message_compression_invalid') from exc
    raise AXRError("message_body_type_invalid")


SCHEMAS = {
    "v4": {"prefix":"Msg_", "id":"rowid", "server":"server_id", "time":"create_time",
           "type":"local_type", "body":"message_content", "direction":"real_sender_id"},
    "v4-is-send": {"prefix":"Msg_", "id":"local_id", "server":"server_id", "time":"create_time",
           "type":"local_type", "body":"message_content", "direction":"is_send"},
    "mac-legacy": {"prefix":"Chat_", "id":"MesLocalID", "server":"MesSvrID", "time":"MesTime",
           "type":"MesType", "body":"Message", "direction":"Des"},
}


class DatabaseAdapter:
    def __init__(self, config, secret_store, *, connection_factory=None):
        self.config,self.secret_store=config,secret_store
        self.factory=connection_factory
        self.bindings={b["conversation_id"]:b for b in config["conversations"]}
        self.connections={}
        self.generations={}

    def _connection(self, shard):
        path=Path(shard["path"]).resolve(strict=True)
        stat=path.stat()
        with path.open("rb") as header:
            salt=header.read(16).hex()
        generation=digest([str(path),stat.st_dev,stat.st_ino,salt])
        if self.generations.get(str(path),generation)!=generation:
            self.close()
            raise AXRError("database_generation_changed_rebaseline_required")
        self.generations[str(path)]=generation
        if str(path) not in self.connections:
            if self.factory:
                connection=self.factory(path)
            else:
                key=self.secret_store.get(shard["key_reference"]).hex()
                connection=CipherConnection(path,self.config["sqlcipher_library"],key,shard["cipher_profile"])
            self.connections[str(path)]=connection
        return self.connections[str(path)],generation

    def status(self):
        return {"mode":"wcdb", "coverage":"explicit_conversation_tables_and_shards",
                "background_read":True, "send_available":False, "key_extraction":False,
                "conversations":len(self.bindings), "shards":len(self.config.get("shards",[]))}

    def search(self, conversation_id, *, query="", sender=None, since=0, until=2**63-1,
               after=None, limit=20):
        if conversation_id not in self.bindings or type(limit) is not int or not 1<=limit<=100:
            raise AXRError("conversation_or_limit_not_authorized")
        if len(query)>256 or since<0 or until<since:
            raise AXRError("invalid_search_range")
        binding=self.bindings[conversation_id]
        schema=SCHEMAS[binding["schema"]]
        hashed=hashlib.md5(conversation_id.encode()).hexdigest() # WeChat table naming; not a security hash.
        table=schema["prefix"]+hashed
        incoming=[]
        for shard in self.config["shards"]:
            db,generation=self._connection(shard)
            try:
                if not db.query("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)):
                    continue
                columns={x["name"] for x in db.query('PRAGMA table_info("'+table+'")')}
                required=set(schema.values())-{schema["prefix"],"rowid"}
                if not required<=columns:
                    raise AXRError("wcdb_schema_not_qualified")
                c={k:'"'+v+'"' for k,v in schema.items() if k!="prefix"}
                compression='"WCDB_CT_message_content"' if 'WCDB_CT_message_content' in columns else '0'
                sender_column='"sender_username"' if 'sender_username' in columns else "NULL"
                sender_ids=binding["schema"]=="v4"
                if sender_ids:
                    # Adapted from chatlog-keeper Name2Id rowid -> username mapping.
                    # Exact bounded lookup, no catalog dump; require owner-provisioned self ID.
                    self_rows=db.query("SELECT rowid FROM Name2Id WHERE user_name=? LIMIT 2",(self.config["account_id"],))
                    if len(self_rows)!=1:raise AXRError("account_identity_not_present_in_shard")
                boundary=after.get(generation,[-1,-1]) if after else [-1,-1]
                sql=(f'SELECT {c["id"]} AS local_id,{c["server"]} AS server_id,{c["time"]} AS created,'
                     f'{c["type"]} AS type,CASE WHEN {c["type"]}=1 THEN {c["body"]} ELSE NULL END AS body,{c["direction"]} AS direction,'
                     f'{compression} AS compression,{sender_column} AS sender FROM "{table}" '
                     f'WHERE {c["time"]}>=? AND {c["time"]}<=? AND ({c["time"]},{c["id"]})>(?,?) '
                     f'ORDER BY {c["time"]},{c["id"]} LIMIT ?')
                for row in db.query(sql,(since,until,int(boundary[0]),int(boundary[1]),limit+1)):
                    # Do not advance beyond unreadable/unsupported records silently.
                    raw_type=row["type"]
                    if raw_type!=1:
                        text=None
                    else:
                        text=decode_text(row["body"],row["compression"])
                    # Schema-specific direction must be explicitly known, never inferred from content.
                    direction=row["direction"]
                    if raw_type!=1:
                        # Unsupported/system records advance the scan cursor only.
                        # No body, sender or direction is inferred or disclosed.
                        actual_sender=None;outgoing=None
                    elif sender_ids:
                        resolved=db.query("SELECT user_name FROM Name2Id WHERE rowid=? LIMIT 2",(int(direction),))
                        if len(resolved)!=1 or not resolved[0]["user_name"]:
                            raise AXRError("sender_identity_unknown")
                        actual_sender=resolved[0]["user_name"]
                        outgoing=actual_sender==self.config["account_id"]
                        if not conversation_id.endswith("@chatroom") and actual_sender not in {conversation_id,self.config["account_id"]}:
                            raise AXRError("private_chat_sender_identity_mismatch")
                    else:
                        if direction not in (0,1):raise AXRError("wcdb_direction_unknown")
                        outgoing=(direction==1) if binding["schema"]=="v4-is-send" else (direction==0)
                        actual_sender=row["sender"] or (self.config["account_id"] if outgoing else
                            conversation_id if not conversation_id.endswith("@chatroom") else None)
                    if conversation_id.endswith("@chatroom") and raw_type==1 and actual_sender is None:
                        # Legacy group bodies carry an explicit sender prefix. Reject ambiguous data.
                        if text and ":\n" in text:
                            actual_sender,text=text.split(":\n",1)
                        else:
                            raise AXRError("group_sender_not_resolved")
                    if conversation_id.endswith("@chatroom") and text and text.startswith(actual_sender+":\n"):
                        text=text[len(actual_sender)+2:]
                    ref=digest([self.config["account_id"],conversation_id,generation,row["local_id"],row["created"]])
                    incoming.append({"reference":ref,"created":row["created"],"local_id":row["local_id"],"server_id":row["server_id"],
                        "generation":generation,"text":text,"sender":actual_sender,"outgoing":outgoing,
                        "matches":bool(text is not None and query in text and (sender is None or sender==actual_sender))})
            finally:
                # Release the page handle, especially FILE_SHARE_DELETE constraints on Windows.
                # Native pager/WAL queries avoid full plaintext export, without pinning a live shard.
                db.close()
                self.connections.pop(str(Path(shard["path"]).resolve()),None)
        incoming.sort(key=lambda x:(x["created"],x["local_id"],x["generation"]))
        scanned=incoming[:limit]
        cursor=dict(after or {})
        for message in scanned:
            cursor[message["generation"]]=[message["created"],message["local_id"]]
        return {"messages":[m for m in scanned if m.pop("matches")],"cursor":cursor,
                "has_more":len(incoming)>limit,"scanned":len(scanned),
                "coverage":self.status()["coverage"],"complete_history":False}

    def cancel(self):
        for connection in list(self.connections.values()):
            if hasattr(connection,"interrupt"):connection.interrupt()

    def close(self):
        for connection in self.connections.values():
            connection.close()
        self.connections.clear()
