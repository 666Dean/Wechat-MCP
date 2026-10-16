// SPDX-License-Identifier: MIT
// Application-owned fixed WCDB operations. No key, SQL, library or path is an
// operation result. The only production key source is AXR's native OS store.
#include "axr/Credentials.hpp"
#include "axr/ProtectedStore.hpp"
#include "axr/Security.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h>
#include <openssl/evp.h>
#include <sqlite3.h>
extern "C" int sqlite3_key(sqlite3*,const void*,int);
#include <chrono>
#include <map>
#include <set>
#include <fstream>
#if defined(__APPLE__)
#include <Security/Security.h>
#endif
#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
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
                    if(type==SQLITE_BLOB)row[name]=Json{{"blob_hex",Hex(value)}};else row[name]=value;}
            }rows.push_back(row);
        }return rows;
    }
    static std::string Hex(std::string_view data){static constexpr char digits[]="0123456789abcdef";std::string out;out.reserve(data.size()*2);for(unsigned char c:data){out+=digits[c>>4];out+=digits[c&15];}return out;}
};
std::string Table(const std::string& id){unsigned char hash[16];unsigned n=0;if(!EVP_Digest(id.data(),id.size(),hash,&n,EVP_md5(),nullptr)||n!=16)throw std::runtime_error("wcdb_table_digest_failed");return "Msg_"+Database::Hex({reinterpret_cast<char*>(hash),16});}
std::vector<std::string> ResourceKeys(const Json& config){std::vector<std::string> keys;for(auto& r:config.at("resources"))keys.push_back(Digest(r.dump()));return keys;}
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
            {"recent",{"kind","query","since"}},{"draft",{"kind"}},
            {"unique_draft",{"kind","text"}}};
        auto permitted=fields.find(kind);
        if(permitted==fields.end())throw std::runtime_error("wcdb_native_operation_not_registered");
        for(auto i=request.begin();i!=request.end();++i)if(!permitted->second.contains(i.key()))throw std::runtime_error("wcdb_native_request_invalid");
        Json result=Json::array();
        for(auto& shard:config.at("shards")){
            auto purpose=shard.at("role").get<std::string>();
            if((kind=="messages"&&purpose!="message")||(kind=="recent"&&purpose!="general")||((kind=="draft"||kind=="unique_draft")&&purpose!="session"))continue;
            if(kind!="messages"&&kind!="recent"&&kind!="draft"&&kind!="unique_draft")throw std::runtime_error("wcdb_native_operation_not_registered");
            std::string key;
#ifndef AXR_SECURITY_RELEASE
            if(!fixtureKeys.empty())key=fixtureKeys.at(shard.at("key_reference"));else
#endif
            key=ProtectedStore(config.at("credential_namespace")).Get(shard.at("key_reference"));
            Database db(api,shard,key);Json rows;
            if(kind=="messages"){
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
            else if(kind=="draft")rows=db.run("SELECT CASE WHEN length(CAST(draft AS BLOB))<=16000 THEN draft ELSE NULL END AS draft,length(CAST(draft AS BLOB)) AS size FROM SessionTable WHERE username=? LIMIT 2",Json::array({id}));
            else {auto text=request.at("text").get<std::string>();if(text.empty()||text.size()>16000)throw std::runtime_error("wcdb_native_draft_budget");rows=db.run("SELECT username,CASE WHEN length(CAST(draft AS BLOB))<=16000 THEN draft ELSE NULL END AS draft FROM SessionTable WHERE instr(draft,?)>0 LIMIT 3",Json::array({text}));if(rows.size()!=1||rows[0]["username"]!=id||rows[0]["draft"]!=text)throw std::runtime_error("wcdb_native_unique_draft_mismatch");}
            result.push_back(Json{{"shard",shard.at("id")},{"rows",rows}});
        }
        return result;
    }
};
#if defined(__APPLE__)
CFStringRef Text(const std::string& text){return CFStringCreateWithBytes(nullptr,reinterpret_cast<const UInt8*>(text.data()),text.size(),kCFStringEncodingUTF8,false);}
Json ImportLegacy(const Json& configuration,const std::string& legacyNamespace){
    // Calling this is possible only inside the protected authority identity.
    // The owner setup review names the old service and exact enrolled files.
    ProtectedStore destination(configuration.at("credential_namespace"));
    Cipher api(configuration.at("sqlcipher_library"));unsigned count=0;
    for(auto& shard:configuration.at("shards")){
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
        try {auto verifyKey=key;Database verify(api,shard,verifyKey);destination.Put(shard.at("key_reference"),key);}
        catch(...){OPENSSL_cleanse(key.data(),key.size());throw;}
        OPENSSL_cleanse(key.data(),key.size());++count;
    }
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
#ifndef AXR_SECURITY_RELEASE
    m.def("fixture_consumer",[](const std::string& witness,const std::string& config,const py::dict& values){std::map<std::string,std::string> keys;for(auto item:values)keys.emplace(py::cast<std::string>(item.first),py::cast<std::string>(item.second));return std::make_unique<WeChatConsumer>(witness,ParseBounded(config),std::move(keys));});
#endif
}
