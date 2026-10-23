// SPDX-License-Identifier: MIT
// Application-owned fixed WCDB operations. No key, SQL, library or path is an
// operation result. The only production key source is AXR's native OS store.
#include "axr/Credentials.hpp"
#include "axr/ProtectedStore.hpp"
#include "axr/Security.hpp"
#include "axr/WindowsInstallation.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h>
#include <openssl/evp.h>
#include <sqlite3.h>
extern "C" int sqlite3_key(sqlite3*,const void*,int);
#include <chrono>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <fstream>
#include <fcntl.h>
#include <sys/stat.h>
#if defined(__APPLE__)
#include <Security/Security.h>
#endif
#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#include <unistd.h>
#endif
namespace py=pybind11;
using namespace Stellaria::AXR;
namespace {
struct Cipher {
#if defined(_WIN32)
    HMODULE image;
#else
    void* image;
#endif
#define FN(n) decltype(&sqlite3_##n) n=nullptr
    FN(open_v2); FN(close_v2); FN(key); FN(prepare_v2); FN(step); FN(finalize); FN(bind_text); FN(bind_int64); FN(column_count); FN(column_name); FN(column_type); FN(column_bytes); FN(column_blob); FN(column_int64); FN(progress_handler); FN(stmt_readonly); FN(busy_timeout);
#undef FN
    explicit Cipher(const std::string& path) {
        if(!Utf8Path(path).is_absolute())throw std::runtime_error("wcdb_cipher_absolute_library_required");
#if defined(_WIN32)
        image=LoadLibraryExW(Utf8Path(path).c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
#define SYM(n) n=reinterpret_cast<decltype(n)>(GetProcAddress(image,"sqlite3_" #n)); if(!n)throw std::runtime_error("wcdb_cipher_symbol_missing")
#else
        image=dlopen(path.c_str(),RTLD_NOW|RTLD_LOCAL);
#define SYM(n) n=reinterpret_cast<decltype(n)>(dlsym(image,"sqlite3_" #n)); if(!n)throw std::runtime_error("wcdb_cipher_symbol_missing")
#endif
        if(!image)throw std::runtime_error("wcdb_cipher_load_failed");
        SYM(open_v2);SYM(close_v2);SYM(key);SYM(prepare_v2);SYM(step);SYM(finalize);SYM(bind_text);SYM(bind_int64);SYM(column_count);SYM(column_name);SYM(column_type);SYM(column_bytes);SYM(column_blob);SYM(column_int64);SYM(progress_handler);SYM(stmt_readonly);SYM(busy_timeout);
#undef SYM
    }
    ~Cipher(){if(image){
#if defined(_WIN32)
        FreeLibrary(image);
#else
        dlclose(image);
#endif
    }}
};
struct Database {
    Cipher& api; sqlite3* db=nullptr;
    std::chrono::steady_clock::time_point deadline;
    Database(Cipher& a,const Json& shard,std::string& key):api(a){
        try {
            if(key.size()!=32)throw std::runtime_error("wcdb_native_key_length");
            const auto path=Utf8Path(shard.at("path").get<std::string>());
            if(!path.is_absolute()||std::filesystem::is_symlink(path))throw std::runtime_error("wcdb_database_path_rejected");
            if(shard.contains("salt")){
                std::ifstream stream(path,std::ios::binary);char salt[16];stream.read(salt,16);
                if(stream.gcount()!=16||Hex({salt,16})!=shard.at("salt").get<std::string>())throw std::runtime_error("wcdb_native_generation_changed");
            }
#ifdef AXR_SECURITY_RELEASE
            else throw std::runtime_error("wcdb_native_generation_pin_required");
#endif
            auto utf8=path.u8string();
            if(api.open_v2(reinterpret_cast<const char*>(utf8.c_str()),&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_FULLMUTEX,nullptr)!=SQLITE_OK)throw std::runtime_error("wcdb_native_open_failed");
            // Existing WCDB references contain a raw 256-bit key, not a
            // passphrase. Preserve SQLCipher's x'..' raw-key semantics rather
            // than silently deriving a different key from the same 32 bytes.
            auto rawKey="x'"+Hex(key)+"'";
            auto keyStatus=api.key(db,rawKey.data(),int(rawKey.size()));
            OPENSSL_cleanse(rawKey.data(),rawKey.size());
            if(keyStatus!=SQLITE_OK)throw std::runtime_error("wcdb_native_key_rejected");
            auto profile=shard.at("cipher_profile").get<std::string>();
            if(profile=="sqlcipher3")run("PRAGMA cipher_compatibility=3");
            else if(profile=="wcdb4-raw") {run("PRAGMA cipher_page_size=4096");run("PRAGMA cipher_hmac_algorithm=HMAC_SHA512");run("PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_SHA512");run("PRAGMA cipher_use_hmac=ON");}
            else if(profile!="sqlcipher4")throw std::runtime_error("wcdb_native_profile_unsupported");
            run("PRAGMA query_only=ON");run("PRAGMA trusted_schema=OFF");run("SELECT count(*) FROM sqlite_master");api.busy_timeout(db,500);
        }catch(...){if(db)api.close_v2(db);db=nullptr;OPENSSL_cleanse(key.data(),key.size());throw;}
        OPENSSL_cleanse(key.data(),key.size());
    }
    ~Database(){if(db)api.close_v2(db);}
    Json run(const std::string& sql,const Json& params=Json::array()){
        sqlite3_stmt* stmt=nullptr;const char* tail=nullptr;
        if(api.prepare_v2(db,sql.c_str(),int(sql.size()),&stmt,&tail)!=SQLITE_OK||!stmt)throw std::runtime_error("wcdb_native_query_failed");
        struct Cleanup{Cipher& a;sqlite3_stmt* s;~Cleanup(){a.finalize(s);}} cleanup{api,stmt};
        // SQL is generated exclusively below. Neither MCP nor Python passes SQL.
        for(size_t i=0;i<params.size();++i){auto& p=params[i];int code;
            if(p.is_number_integer())code=api.bind_int64(stmt,int(i+1),p.get<int64_t>());
            else if(p.is_string()){const auto& text=p.get_ref<const std::string&>();code=api.bind_text(stmt,int(i+1),text.data(),int(text.size()),SQLITE_TRANSIENT);}
            else throw std::runtime_error("wcdb_native_parameter_type");
            if(code!=SQLITE_OK)throw std::runtime_error("wcdb_native_parameter_failed");
        }
        deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        api.progress_handler(db,1000,[](void* self){return std::chrono::steady_clock::now()>static_cast<Database*>(self)->deadline?1:0;},this);
        struct Stop{Database& s;~Stop(){s.api.progress_handler(s.db,0,nullptr,nullptr);}} stop{*this};
        Json rows=Json::array();size_t bytes=0;
        for(;;){int code=api.step(stmt);if(code==SQLITE_DONE)break;if(code!=SQLITE_ROW)throw std::runtime_error("wcdb_native_read_failed");
            if(rows.size()>=1001)throw std::runtime_error("wcdb_native_row_budget");Json row=Json::object();
            for(int c=0;c<api.column_count(stmt);++c){std::string name=api.column_name(stmt,c);int type=api.column_type(stmt,c);
                if(type==SQLITE_NULL)row[name]=nullptr;
                else if(type==SQLITE_INTEGER)row[name]=api.column_int64(stmt,c);
                else {int n=api.column_bytes(stmt,c);if(n<0||n>1024*1024||bytes+size_t(n)>480000)throw std::runtime_error("wcdb_native_byte_budget");bytes+=n;
                    auto data=static_cast<const char*>(api.column_blob(stmt,c));std::string value(data?data:"",n);
                    // WCDB may retain SQLite's TEXT affinity for compressed
                    // message bytes. Never serialize those bytes as UTF-8.
                    if(type==SQLITE_BLOB||name=="body")row[name]=Json{{"blob_hex",Hex(value)}};else row[name]=value;}
            }rows.push_back(row);
        }return rows;
    }
    static std::string Hex(std::string_view data){static constexpr char digits[]="0123456789abcdef";std::string out;out.reserve(data.size()*2);for(unsigned char c:data){out+=digits[c>>4];out+=digits[c&15];}return out;}
};
std::string Table(const std::string& id){unsigned char hash[16];unsigned n=0;if(!EVP_Digest(id.data(),id.size(),hash,&n,EVP_md5(),nullptr)||n!=16)throw std::runtime_error("wcdb_table_digest_failed");return "Msg_"+Database::Hex({reinterpret_cast<char*>(hash),16});}
std::vector<std::string> ResourceKeys(const Json& config){std::vector<std::string> keys;for(auto& r:config.at("resources"))keys.push_back(Digest(r.dump()));return keys;}
std::string NativeKeyName(const std::string& reference){return "wcdb-"+Digest(reference);}
#if defined(__APPLE__)
struct EncryptedSnapshot {
    std::filesystem::path directory,path;
    struct Stamp {dev_t device;ino_t inode;off_t size;timespec modified,changed;};
    static Stamp stamp(const struct stat& s){return {s.st_dev,s.st_ino,s.st_size,s.st_mtimespec,s.st_ctimespec};}
    static bool same(const Stamp& a,const Stamp& b){return a.device==b.device&&a.inode==b.inode&&a.size==b.size&&a.modified.tv_sec==b.modified.tv_sec&&a.modified.tv_nsec==b.modified.tv_nsec&&a.changed.tv_sec==b.changed.tv_sec&&a.changed.tv_nsec==b.changed.tv_nsec;}
    static Stamp copy(const std::filesystem::path& source,const std::filesystem::path& target,size_t maximum){
        int input=open(source.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
        if(input<0)throw std::runtime_error("wcdb_snapshot_source_unavailable");
        struct Close {int fd;~Close(){close(fd);}} closeInput{input};
        struct stat first{};if(fstat(input,&first)||!S_ISREG(first.st_mode)||first.st_size<0||uint64_t(first.st_size)>maximum)throw std::runtime_error("wcdb_snapshot_budget_or_type");
        int output=open(target.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
        if(output<0)throw std::runtime_error("wcdb_snapshot_create_failed");
        Close closeOutput{output};char buffer[65536];size_t total=0;
        for(;;){auto n=read(input,buffer,sizeof buffer);if(n<0)throw std::runtime_error("wcdb_snapshot_read_failed");if(!n)break;
            total+=size_t(n);if(total>maximum)throw std::runtime_error("wcdb_snapshot_budget_or_type");
            size_t offset=0;while(offset<size_t(n)){auto written=write(output,buffer+offset,size_t(n)-offset);if(written<=0)throw std::runtime_error("wcdb_snapshot_write_failed");offset+=size_t(written);}}
        struct stat after{},named{};if(fstat(input,&after)||lstat(source.c_str(),&named)||!same(stamp(first),stamp(after))||!same(stamp(first),stamp(named))||total!=size_t(first.st_size))throw std::runtime_error("wcdb_snapshot_source_changed");
        return stamp(first);
    }
    explicit EncryptedSnapshot(const std::filesystem::path& source){
        char pattern[]="/private/tmp/axr-encrypted-wcdb-XXXXXX";auto created=mkdtemp(pattern);
        if(!created)throw std::runtime_error("wcdb_snapshot_create_failed");directory=created;path=directory/"source.db";
        try {
            auto before=copy(source,path,128*1024*1024);auto wal=source;wal+="-wal";struct stat info{};
            const bool hasWal=lstat(wal.c_str(),&info)==0;std::optional<Stamp> walStamp;
            if(hasWal)walStamp=copy(wal,path.string()+"-wal",64*1024*1024);
            struct stat after{};if(lstat(source.c_str(),&after)||!same(before,stamp(after)))throw std::runtime_error("wcdb_snapshot_source_changed");
            if(hasWal){if(lstat(wal.c_str(),&after)||!same(*walStamp,stamp(after)))throw std::runtime_error("wcdb_snapshot_source_changed");}
            else if(lstat(wal.c_str(),&after)==0)throw std::runtime_error("wcdb_snapshot_source_changed");
            // Deliberately do not copy shared-memory indexes. SQLCipher builds
            // its own index from committed frames in this encrypted local copy.
        }catch(...){std::error_code error;std::filesystem::remove_all(directory,error);throw;}
    }
    ~EncryptedSnapshot(){std::error_code error;std::filesystem::remove_all(directory,error);}
};
#endif
class WeChatConsumer final:public CredentialConsumer {
    Json config;Cipher api;
#ifndef AXR_SECURITY_RELEASE
    std::map<std::string,std::string> fixtureKeys;
#endif
public:
    WeChatConsumer(std::string witness,Json c):CredentialConsumer(witness,ResourceKeys(c),{"database.query"}),config(std::move(c)),api(config.at("sqlcipher_library")){}
#ifndef AXR_SECURITY_RELEASE
    WeChatConsumer(std::string witness,Json c,std::map<std::string,std::string> keys):WeChatConsumer(std::move(witness),std::move(c)){fixtureKeys=std::move(keys);}
#endif
protected:
    Json Perform(const Json& resource,const std::string&,const Json& request) override {
        if(resource.at("platform")!="wechat"||resource.at("account_id")!=config.at("account_id"))throw std::runtime_error("wcdb_native_account_mismatch");
        auto kind=request.at("kind").get<std::string>();auto id=resource.at("conversation_id").get<std::string>();
        if(id.find('@')!=std::string::npos&&id!=config.at("account_id").get<std::string>())throw std::runtime_error("wcdb_native_private_chat_required");
        const std::map<std::string,std::set<std::string>> fields={
            {"messages",{"kind","since","until","after","cursors","limit"}},
            {"recent",{"kind","query","since"}},{"draft",{"kind"}},{"session_schema",{"kind"}},{"session_state",{"kind"}},
            {"message_state",{"kind","isolated_snapshot"}},
            {"activity",{"kind","since","after","limit"}},
            {"catalog",{"kind","offset","limit"}},
            {"unique_draft",{"kind","text"}}};
        auto permitted=fields.find(kind);
        if(permitted==fields.end())throw std::runtime_error("wcdb_native_operation_not_registered");
        for(auto i=request.begin();i!=request.end();++i)if(!permitted->second.contains(i.key()))throw std::runtime_error("wcdb_native_request_invalid");
        Json activityParams;std::string activitySql;
        if(kind=="activity"){
            // Account-level local metadata only. Never return summaries, names,
            // drafts or bodies, and never accept caller SQL or recipient lists.
            if(id!=config.at("account_id").get<std::string>())throw std::runtime_error("wcdb_native_account_resource_required");
            auto since=request.at("since"),after=request.at("after"),limit=request.at("limit");
            if(!since.is_number_integer()||since.get<int64_t>()<0||!limit.is_number_integer()||limit.get<int64_t>()<1||limit.get<int64_t>()>128||
               !after.is_array()||after.size()!=2||!after[0].is_number_integer()||after[0].get<int64_t>()<0||!after[1].is_string()||after[1].get<std::string>().size()>256)
                throw std::runtime_error("wcdb_native_activity_range");
            std::set<std::string> ids;
            for(auto& r:config.at("resources")){
                auto value=r.at("conversation_id").get<std::string>();
                if(r.at("platform")!="wechat"||r.at("account_id")!=config.at("account_id")||value.empty()||value.size()>256||
                   (value.find('@')!=std::string::npos&&value!=id)||!ids.insert(value).second)
                    throw std::runtime_error("wcdb_native_activity_catalog");
            }
            if(ids.empty()||ids.size()>4096)throw std::runtime_error("wcdb_native_activity_catalog");
            activitySql="SELECT username AS conversation_id,last_timestamp AS updated,last_msg_locald_id AS local_id FROM SessionTable WHERE username IN (";
            activityParams=Json::array();
            for(auto& value:ids){if(!activityParams.empty())activitySql+=",";activitySql+="?";activityParams.push_back(value);}
            activitySql+=") AND last_timestamp>=? AND (last_timestamp,username)>(?,?) ORDER BY last_timestamp,username LIMIT ?";
            for(auto& value:Json::array({since,after[0],after[1],limit.get<int64_t>()+1}))activityParams.push_back(value);
        }
        Json result=Json::array();
        for(auto& shard:config.at("shards")){
            auto purpose=shard.at("role").get<std::string>();
            if(kind=="catalog"&&purpose!="contact")continue;
            if(kind!="catalog"&&purpose=="contact")continue;
            if(((kind=="messages"||kind=="message_state")&&purpose!="message")||(kind=="recent"&&purpose!="general")||((kind=="draft"||kind=="unique_draft"||kind=="session_schema"||kind=="session_state"||kind=="activity")&&purpose!="session"))continue;
            auto selected=shard;
#if defined(__APPLE__)
            std::unique_ptr<EncryptedSnapshot> snapshot;
            if(kind=="message_state"&&request.value("isolated_snapshot",false)){
                snapshot=std::make_unique<EncryptedSnapshot>(Utf8Path(shard.at("path").get<std::string>()));selected["path"]=snapshot->path.string();
            }
#else
            if(kind=="message_state"&&request.value("isolated_snapshot",false))throw std::runtime_error("wcdb_snapshot_platform_unqualified");
#endif
            std::string key;
#ifndef AXR_SECURITY_RELEASE
            if(!fixtureKeys.empty())key=fixtureKeys.at(shard.at("key_reference"));else
#endif
            key=ProtectedStore(config.at("credential_namespace")).Get(NativeKeyName(shard.at("key_reference")));
            Database db(api,selected,key);Json rows;
            if(kind=="catalog"){
                auto offset=request.value("offset",0),limit=request.value("limit",1000);
                if(offset<0||offset>10000||limit<1||limit>1000)throw std::runtime_error("wcdb_native_catalog_budget");
                auto self=db.run("SELECT username FROM contact WHERE username=? LIMIT 2",Json::array({config.at("account_id")}));
                if(self.size()!=1)throw std::runtime_error("wcdb_native_self_identity_missing");
                rows=db.run("SELECT username,nick_name,remark FROM contact WHERE delete_flag=0 ORDER BY username LIMIT ? OFFSET ?",Json::array({limit,offset}));
            }else if(kind=="message_state"){
                // Fixed owner-only readback diagnostics. Never enumerate other
                // recipients, return content, or accept SQL/table parameters.
                auto table=Table(id);db.run("BEGIN");
                auto present=db.run("SELECT name FROM sqlite_master WHERE type='table' AND name=?",Json::array({table}));
                if(present.empty())rows=Json::array({Json{{"table_present",false}}});
                else {
                    rows=db.run("SELECT 1 AS table_present,count(*) AS records,max(create_time) AS latest_created,max(rowid) AS latest_local_id FROM \""+table+"\"");
                    auto latest=db.run("SELECT m.create_time AS created,m.local_type AS type,m.server_id,m.real_sender_id AS sender_index,n.user_name=? AS sender_is_self,n.user_name=? AS sender_is_peer FROM \""+table+"\" m LEFT JOIN Name2Id n ON n.rowid=m.real_sender_id ORDER BY m.create_time DESC,m.rowid DESC LIMIT 3",Json::array({config.at("account_id"),id}));
                    rows[0]["latest_metadata"]=latest;
                }
                // Inspect only tables belonging to this exact recipient hash.
                // Schema names are diagnostic metadata, never caller-selected
                // SQL or a license to read another recipient's records.
                auto candidates=db.run("SELECT name FROM sqlite_master WHERE type='table' AND instr(lower(name),?)>0 ORDER BY name LIMIT 17",Json::array({table.substr(4)}));
                if(candidates.size()>16)throw std::runtime_error("wcdb_native_target_schema_budget");
                Json schemas=Json::array();
                for(auto& candidate:candidates){
                    auto name=candidate.at("name").get<std::string>();
                    if(name.empty()||name.size()>128||name.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")!=std::string::npos)throw std::runtime_error("wcdb_native_target_schema_unqualified");
                    schemas.push_back(Json{{"name",name},{"columns",db.run("SELECT name,type FROM pragma_table_info(?) LIMIT 64",Json::array({name}))}});
                }
                rows[0]["target_schemas"]=schemas;
                rows[0]["journal_mode"]=db.run("PRAGMA journal_mode");
                rows[0]["name_index_schema"]=db.run("SELECT name,type FROM pragma_table_info('Name2Id') LIMIT 32");
                rows[0]["target_name_index"]=db.run("SELECT rowid AS name_id FROM Name2Id WHERE user_name=? LIMIT 2",Json::array({id}));
                rows[0]["send_index_schema"]=db.run("SELECT name,type FROM pragma_table_info('SendInfo') LIMIT 32");
                rows[0]["full_scan"]=present.empty()?Json::array():db.run("SELECT count(*) AS records,max(create_time) AS latest_created,max(rowid) AS latest_local_id FROM \""+table+"\" NOT INDEXED");
                rows[0]["source_path_fingerprint"]=Digest(shard.at("path").get<std::string>());
                auto auxiliary=db.run("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'Msg_%' ORDER BY name LIMIT 65");
                if(auxiliary.size()>64)throw std::runtime_error("wcdb_native_auxiliary_schema_budget");
                Json auxiliarySchemas=Json::array();
                for(auto& entry:auxiliary){
                    auto name=entry.at("name").get<std::string>();
                    if(name.empty()||name.size()>80||name.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")!=std::string::npos||name.find("wxid_")!=std::string::npos||std::regex_search(name,std::regex("[a-fA-F0-9]{32}")))continue;
                    auxiliarySchemas.push_back(Json{{"name",name},{"columns",db.run("SELECT name,type FROM pragma_table_info(?) LIMIT 64",Json::array({name}))}});
                }
                rows[0]["auxiliary_schemas"]=auxiliarySchemas;
                if(!db.run("SELECT name FROM sqlite_master WHERE type='table' AND name='MessageGroupTimeInfo'").empty()){
                    // An empty exact join cannot distinguish an unused feature
                    // from a namespace mismatch. Return only the table's size;
                    // never enumerate another conversation's group values.
                    rows[0]["group_index_size"]=db.run("SELECT count(*) AS records FROM MessageGroupTimeInfo");
                    rows[0]["target_groups"]=db.run("SELECT group_id,create_time,initial_sort_seq,birth_time FROM MessageGroupTimeInfo WHERE chatname_id=(SELECT rowid FROM Name2Id WHERE user_name=?) ORDER BY create_time LIMIT 65",Json::array({id}));
                    if(rows[0]["target_groups"].size()>64)throw std::runtime_error("wcdb_native_target_group_budget");
                }
#if defined(__APPLE__)
                struct stat sourceInfo{};
                if(lstat(Utf8Path(shard.at("path").get<std::string>()).c_str(),&sourceInfo))throw std::runtime_error("wcdb_native_source_unavailable");
                rows[0]["source_identity"]=Json{{"device",sourceInfo.st_dev},{"inode",sourceInfo.st_ino},{"size",sourceInfo.st_size}};
#endif
            }else if(kind=="messages"){
                auto table=Table(id);db.run("BEGIN");auto present=db.run("SELECT name FROM sqlite_master WHERE type='table' AND name=?",Json::array({table}));if(present.empty())continue;
                auto columns=db.run("PRAGMA table_info(\""+table+"\")");std::set<std::string> names;for(auto& c:columns)names.insert(c.at("name"));
                for(auto name:{"server_id","create_time","local_type","message_content","real_sender_id"})if(!names.contains(name))throw std::runtime_error("wcdb_native_schema_unqualified");
                auto self=db.run("SELECT rowid FROM Name2Id WHERE user_name=? LIMIT 2",Json::array({config.at("account_id")}));if(self.size()!=1)throw std::runtime_error("wcdb_native_self_identity_missing");
                int limit=request.value("limit",6);if(limit<1||limit>100)throw std::runtime_error("wcdb_native_page_budget");
                auto cursors=request.value("cursors",Json::object()); if(!cursors.is_object())throw std::runtime_error("wcdb_native_cursor_invalid"); auto after=cursors.value(shard.at("id").get<std::string>(),request.value("after",Json::array({-1,-1})));if(!after.is_array()||after.size()!=2||!after[0].is_number_integer()||!after[1].is_number_integer())throw std::runtime_error("wcdb_native_cursor_invalid");
                auto compression=names.contains("WCDB_CT_message_content")?"m.WCDB_CT_message_content":"0";
                rows=db.run("SELECT m.rowid AS local_id,m.server_id,m.create_time AS created,m.local_type AS type,CASE WHEN m.local_type=1 OR (m.local_type & 65535)=49 THEN m.message_content ELSE NULL END AS body,m.real_sender_id AS direction,"+std::string(compression)+" AS compression,n.user_name AS sender FROM \""+table+"\" m LEFT JOIN Name2Id n ON n.rowid=m.real_sender_id WHERE m.create_time>=? AND m.create_time<=? AND (m.create_time,m.rowid)>(?,?) ORDER BY m.create_time,m.rowid LIMIT ?",Json::array({request.value("since",int64_t(0)),request.value("until",INT64_MAX),after[0],after[1],limit+1}));
                for(auto& row:rows)if(!row["body"].is_null()&&(row["sender"].is_null()||(row["sender"]!=id&&row["sender"]!=config.at("account_id"))))throw std::runtime_error("wcdb_native_sender_identity_mismatch");
            }else if(kind=="recent")rows=db.run("SELECT username,query,last_click_time FROM SearchRecent WHERE query=? AND last_click_time>=? LIMIT 3",Json::array({request.at("query"),request.at("since")}));
            else if(kind=="session_schema")rows=db.run("SELECT name,type FROM pragma_table_info('SessionTable') LIMIT 64");
            else if(kind=="session_state")rows=db.run("SELECT last_timestamp AS updated,last_msg_locald_id AS local_id,last_msg_type AS type,last_msg_sub_type AS subtype FROM SessionTable WHERE username=? LIMIT 2",Json::array({id}));
            else if(kind=="activity")rows=db.run(activitySql,activityParams);
            else if(kind=="draft")rows=db.run("SELECT CASE WHEN length(CAST(draft AS BLOB))<=16000 THEN draft ELSE NULL END AS draft,length(CAST(draft AS BLOB)) AS size FROM SessionTable WHERE username=? LIMIT 2",Json::array({id}));
            else {auto text=request.at("text").get<std::string>();if(text.empty()||text.size()>16000)throw std::runtime_error("wcdb_native_draft_budget");rows=db.run("SELECT username,CASE WHEN length(CAST(draft AS BLOB))<=16000 THEN draft ELSE NULL END AS draft FROM SessionTable WHERE instr(draft,?)>0 LIMIT 3",Json::array({text}));if(rows.size()!=1||rows[0]["username"]!=id||rows[0]["draft"]!=text)throw std::runtime_error("wcdb_native_unique_draft_mismatch");}
            result.push_back(Json{{"shard",shard.at("id")},{"rows",rows}});
        }
        return result;
    }
};
#if defined(__APPLE__)
CFStringRef Text(const std::string& text){return CFStringCreateWithBytes(nullptr,reinterpret_cast<const UInt8*>(text.data()),text.size(),kCFStringEncodingUTF8,false);}
#endif
template<bool Fixture=false> Json ImportOwnerFile(const Json& configuration,const Json& source){
    std::unique_ptr<ProtectedStore> destination;
    if constexpr(!Fixture)destination=std::make_unique<ProtectedStore>(configuration.at("credential_namespace"));
    Cipher api(configuration.at("sqlcipher_library"));unsigned count=0;
    // Authenticate the native store identity before touching the selected file.
    try{if constexpr(!Fixture){auto existing=destination->Get(NativeKeyName(configuration.at("shards").at(0).at("key_reference")));OPENSSL_cleanse(existing.data(),existing.size());}}
    catch(const std::runtime_error& error){if(std::string_view(error.what())!="owner_secret_not_provisioned")throw;}
    auto path=Utf8Path(source.at("path").get<std::string>());
    if(!path.is_absolute())throw std::runtime_error("wcdb_import_path_invalid");
#if defined(_WIN32)
    if(path.wstring().rfind(L"\\\\",0)==0||path.lexically_normal()!=path)throw std::runtime_error("wcdb_import_path_invalid");
    for(auto node=path;!node.empty();node=node.parent_path()){
        auto attributes=GetFileAttributesW(node.c_str());
        if(attributes==INVALID_FILE_ATTRIBUTES||(attributes&FILE_ATTRIBUTE_REPARSE_POINT))throw std::runtime_error("wcdb_import_path_invalid");
        if(node==node.root_path())break;
    }
    // Deny concurrent mutation/rename for the complete native read. Never
    // inherit this handle or expose file bytes to the Python caller.
    auto handle=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr);
    if(handle==INVALID_HANDLE_VALUE)throw std::runtime_error("wcdb_import_file_unavailable");
    struct Close{HANDLE handle;~Close(){CloseHandle(handle);}} closeFile{handle};
    BY_HANDLE_FILE_INFORMATION info{};
    if(!GetFileInformationByHandle(handle,&info)||GetFileType(handle)!=FILE_TYPE_DISK||
        (info.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))||info.nNumberOfLinks!=1||
        info.nFileSizeHigh||info.nFileSizeLow<1||info.nFileSizeLow>65536)throw std::runtime_error("wcdb_import_file_invalid");
    std::string raw(info.nFileSizeLow,'\0');
    struct Erase{std::string& value;~Erase(){OPENSSL_cleanse(value.data(),value.size());}} erase{raw};
    DWORD received=0;
    if(!ReadFile(handle,raw.data(),DWORD(raw.size()),&received,nullptr)||received!=raw.size()||Digest(raw)!=source.at("sha256").get<std::string>())
        throw std::runtime_error("wcdb_import_file_changed");
#else
    for(auto node=path;!node.empty();node=node.parent_path()){
        struct stat info{};if(lstat(node.c_str(),&info)||S_ISLNK(info.st_mode))throw std::runtime_error("wcdb_import_path_invalid");
        if(node==node.root_path())break;
    }
    int fd=open(path.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0)throw std::runtime_error("wcdb_import_file_unavailable");
    struct Close{int fd;~Close(){close(fd);}} closeFile{fd};
    struct stat info{};if(fstat(fd,&info)||!S_ISREG(info.st_mode)||info.st_nlink!=1||info.st_size<1||info.st_size>65536)
        throw std::runtime_error("wcdb_import_file_invalid");
    std::string raw(size_t(info.st_size),'\0');
    struct Erase{std::string& value;~Erase(){OPENSSL_cleanse(value.data(),value.size());}} erase{raw};
    if(read(fd,raw.data(),raw.size())!=ssize_t(raw.size())||Digest(raw)!=source.at("sha256").get<std::string>())
        throw std::runtime_error("wcdb_import_file_changed");
#endif
    // Either one owner-supplied raw key, or {"keys": {salt_hex: key_hex}}.
    // No executable format, process inspection, key export or caller SQL.
    std::map<std::string,std::string> values;bool password=false;
    struct EraseValues{std::map<std::string,std::string>& values;~EraseValues(){for(auto& [_,v]:values)OPENSSL_cleanse(v.data(),v.size());}} eraseValues{values};
    if(raw.find_first_not_of("0123456789abcdefABCDEF\r\n \t")==std::string::npos){
        auto start=raw.find_first_not_of("\r\n \t"),end=raw.find_last_not_of("\r\n \t");
        if(start!=std::string::npos)values["*"]=raw.substr(start,end-start+1);
    }else{
        Json decoded;
        try{decoded=Json::parse(raw);}catch(...){throw std::runtime_error("wcdb_import_format_invalid");}
        struct EraseDecoded {
            Json& value;
            static void erase(Json& v){
                if(v.is_string()){auto& text=v.get_ref<std::string&>();OPENSSL_cleanse(text.data(),text.size());}
                else if(v.is_object()||v.is_array())for(auto& child:v)erase(child);
            }
            ~EraseDecoded(){erase(value);}
        } eraseDecoded{decoded};
        if(!decoded.is_object()||!decoded.contains("keys")||!decoded["keys"].is_object()||decoded["keys"].empty()||decoded["keys"].size()>128)
            throw std::runtime_error("wcdb_import_format_invalid");
        if(decoded.size()!=1){
            if(decoded.size()!=3||!decoded.contains("version")||decoded["version"]!=1||!decoded["version"].is_number_integer()||
                !decoded.contains("key_mode")||(decoded["key_mode"]!="raw"&&decoded["key_mode"]!="password"))throw std::runtime_error("wcdb_import_format_invalid");
            password=decoded["key_mode"]=="password";
        }
        for(auto it=decoded["keys"].begin();it!=decoded["keys"].end();++it){
            if(it.key().size()!=32||!it.value().is_string())throw std::runtime_error("wcdb_import_format_invalid");
            values[it.key()]=it.value().get<std::string>();
        }
    }
    std::map<std::string,std::string> verified;EraseValues eraseVerified{verified};
    if(configuration.at("shards").empty()||configuration.at("shards").size()>128)throw std::runtime_error("wcdb_import_shard_budget");
    for(auto& shard:configuration.at("shards")){
        auto item=values.find(shard.at("salt").get<std::string>());if(item==values.end())item=values.find("*");
        if(item==values.end()||item->second.size()!=64||item->second.find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)
            throw std::runtime_error("wcdb_import_key_missing_or_invalid");
        std::string key(32,'\0');for(size_t i=0;i<32;++i)key[i]=char(std::stoul(item->second.substr(i*2,2),nullptr,16));
        Erase eraseKey{key};
        if(password){
            auto saltHex=shard.at("salt").get<std::string>();
            if(saltHex.size()!=32||saltHex.find_first_not_of("0123456789abcdef")!=std::string::npos)throw std::runtime_error("wcdb_import_salt_invalid");
            std::string salt(16,'\0');for(size_t i=0;i<16;++i)salt[i]=char(std::stoul(saltHex.substr(i*2,2),nullptr,16));
            std::string derived(32,'\0');Erase eraseDerived{derived};
            if(!PKCS5_PBKDF2_HMAC(key.data(),int(key.size()),reinterpret_cast<const unsigned char*>(salt.data()),int(salt.size()),256000,EVP_sha512(),32,
                reinterpret_cast<unsigned char*>(derived.data())))throw std::runtime_error("wcdb_import_derivation_failed");
            key=derived;
        }
        auto verifyKey=key;Database verify(api,shard,verifyKey);
        auto name=NativeKeyName(shard.at("key_reference"));
        auto [entry,inserted]=verified.emplace(name,key);if(!inserted&&entry->second!=key)throw std::runtime_error("wcdb_import_existing_key_conflict");
        if constexpr(!Fixture){
            try{auto existing=destination->Get(name);Erase eraseExisting{existing};if(existing!=key)throw std::runtime_error("wcdb_import_existing_key_conflict");}
            catch(const std::runtime_error& error){if(std::string_view(error.what())!="owner_secret_not_provisioned")throw;}
        }
        ++count;
    }
    // Validate every source/database and existing destination before writing.
    // OS-store failures can leave identical partial keys; reruns never replace.
    if constexpr(!Fixture)for(auto& [name,key]:verified)destination->Put(name,key);
    return Json{{"verified_credentials",count},{"raw_keys_exported",false},{"legacy_permissions_restored",false}};
}
#if defined(__APPLE__)
Json ImportLegacy(const Json& configuration,const std::string& legacyNamespace){
    // Calling this is possible only inside the protected authority identity.
    // The owner setup review names the old service and exact enrolled files.
    ProtectedStore destination(configuration.at("credential_namespace"));
    Cipher api(configuration.at("sqlcipher_library"));unsigned count=0;
    for(auto& shard:configuration.at("shards")){
        // Continue a verified partial migration without another legacy-item
        // access dialog. Existing but invalid keys fail; never guess/replace.
        try {
            auto key=destination.Get(NativeKeyName(shard.at("key_reference")));
            Database verify(api,shard,key);++count;continue;
        }catch(const std::runtime_error& error){
            if(std::string_view(error.what())!="owner_secret_not_provisioned")throw;
        }
        auto service=Text(legacyNamespace),account=Text(shard.at("key_reference"));
        const void* keys[]={kSecClass,kSecAttrService,kSecAttrAccount,kSecReturnData,kSecMatchLimit};
        const void* values[]={kSecClassGenericPassword,service,account,kCFBooleanTrue,kSecMatchLimitOne};
        auto query=CFDictionaryCreate(nullptr,keys,values,5,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
        CFTypeRef result=nullptr;auto status=SecItemCopyMatching(query,&result);CFRelease(query);CFRelease(service);CFRelease(account);
        if(status!=errSecSuccess||!result)throw std::runtime_error("wcdb_native_legacy_access_denied");
        if(CFGetTypeID(result)!=CFDataGetTypeID()){CFRelease(result);throw std::runtime_error("wcdb_native_legacy_record_invalid");}
        auto data=static_cast<CFDataRef>(result);std::string encoded(reinterpret_cast<const char*>(CFDataGetBytePtr(data)),CFDataGetLength(data));CFRelease(result);
        if(encoded.size()!=44||encoded.back()!='=')throw std::runtime_error("wcdb_native_legacy_record_invalid");
        std::string key(33,'\0');int n=EVP_DecodeBlock(reinterpret_cast<unsigned char*>(key.data()),reinterpret_cast<const unsigned char*>(encoded.data()),int(encoded.size()));OPENSSL_cleanse(encoded.data(),encoded.size());
        if(n!=33){OPENSSL_cleanse(key.data(),key.size());throw std::runtime_error("wcdb_native_legacy_record_invalid");}key.resize(32);
        try {auto verifyKey=key;Database verify(api,shard,verifyKey);destination.Put(NativeKeyName(shard.at("key_reference")),key);}
        catch(...){OPENSSL_cleanse(key.data(),key.size());throw;}
        OPENSSL_cleanse(key.data(),key.size());++count;
    }
    return Json{{"verified_credentials",count},{"raw_keys_exported",false},{"legacy_permissions_restored",false}};
}
#endif
#if defined(_WIN32)
Json ImportWindowsLegacy(const Json& configuration,const std::string& space,const std::string& owner){
    ProtectedStore destination(configuration.at("credential_namespace"));
    Cipher api(configuration.at("sqlcipher_library"));unsigned count=0;
    std::map<std::string,std::string> verified;
    struct Erase{std::map<std::string,std::string>& values;~Erase(){for(auto& [_,v]:values)OPENSSL_cleanse(v.data(),v.size());}} erase{verified};
    if(space.rfind("Stellaria.AXR.",0)!=0||configuration.at("shards").empty()||configuration.at("shards").size()>128)throw std::runtime_error("wcdb_import_request_invalid");
    for(auto& shard:configuration.at("shards")){
        auto reference=shard.at("key_reference").get<std::string>(),name=NativeKeyName(reference);std::string key;
        struct Clean{std::string& v;~Clean(){OPENSSL_cleanse(v.data(),v.size());}} clean{key};
        try{key=destination.Get(name);}
        catch(const std::runtime_error& error){
            if(std::string_view(error.what())!="owner_secret_not_provisioned")throw;
            auto encoded=ReadWindowsOwnerCredential(owner,space,reference);Clean cleanEncoded{encoded};
            if(encoded.size()!=44||encoded.back()!='='||encoded.substr(0,43).find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")!=std::string::npos)
                throw std::runtime_error("wcdb_native_legacy_record_invalid");
            key.resize(33);if(EVP_DecodeBlock(reinterpret_cast<unsigned char*>(key.data()),reinterpret_cast<const unsigned char*>(encoded.data()),44)!=33)
                throw std::runtime_error("wcdb_native_legacy_record_invalid");key.resize(32);
        }
        auto copy=key;Database verify(api,shard,copy);auto [entry,inserted]=verified.emplace(name,key);
        if(!inserted&&entry->second!=key)throw std::runtime_error("wcdb_import_existing_key_conflict");++count;
    }
    for(auto& [name,key]:verified)destination.Put(name,key);
    return Json{{"verified_credentials",count},{"raw_keys_exported",false},{"legacy_permissions_restored",false}};
}
#endif
}
PYBIND11_MODULE(_wechat_credentials,m){
    py::module_::import("axr._axr_native");
    py::class_<WeChatConsumer,CredentialConsumer>(m,"WeChatConsumer").def(py::init([](const std::string& witness,const std::string& config){return std::make_unique<WeChatConsumer>(witness,ParseBounded(config));}));
#if defined(__APPLE__)
    m.def("import_legacy_credentials",[](const std::string& config,const std::string& legacyNamespace){return ImportLegacy(ParseBounded(config),legacyNamespace).dump();});
#endif
#if defined(_WIN32)
    m.def("import_legacy_owner_credentials",[](const std::string& config,const std::string& space,const std::string& owner){return ImportWindowsLegacy(ParseBounded(config),space,owner).dump();});
#endif
    m.def("import_owner_credentials",[](const std::string& config,const std::string& source){return ImportOwnerFile(ParseBounded(config),ParseBounded(source)).dump();});
#ifndef AXR_SECURITY_RELEASE
    // Synthetic encrypted-file tests only; never compiled into release code.
    m.def("fixture_verify_owner_file",[](const std::string& config,const std::string& source){return ImportOwnerFile<true>(ParseBounded(config),ParseBounded(source)).dump();});
    m.def("fixture_consumer",[](const std::string& witness,const std::string& config,const py::dict& values){std::map<std::string,std::string> keys;for(auto item:values)keys.emplace(py::cast<std::string>(item.first),py::cast<std::string>(item.second));return std::make_unique<WeChatConsumer>(witness,ParseBounded(config),std::move(keys));});
#endif
}
