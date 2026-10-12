// SPDX-License-Identifier: AGPL-3.0-only
#include "axr/Core.hpp"
#include "axr/Commit.h"
#include <cmath>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>
#include <sqlite3.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <map>
#include <set>
#include <stdexcept>

namespace Stellaria::AXR {
namespace {
[[noreturn]] void Fail(const char* code) { throw std::runtime_error(code); }
std::string Hex(const unsigned char* bytes, std::size_t length) {
    constexpr char digits[]="0123456789abcdef";
    std::string result(length*2,'0');
    for(std::size_t i=0;i<length;++i) {result[2*i]=digits[bytes[i]>>4];result[2*i+1]=digits[bytes[i]&15];}
    return result;
}
void Exec(sqlite3* db, const char* sql) {
    if(sqlite3_exec(db,sql,nullptr,nullptr,nullptr)!=SQLITE_OK) Fail("trusted_store_operation_failed");
}
struct Statement {
    sqlite3_stmt* s{};
    Statement(sqlite3* db, const char* sql) { if(sqlite3_prepare_v2(db,sql,-1,&s,nullptr)!=SQLITE_OK) Fail("trusted_store_query_failed"); }
    ~Statement() { sqlite3_finalize(s); }
    void Text(int n,std::string_view v) { if(sqlite3_bind_text(s,n,v.data(),int(v.size()),SQLITE_TRANSIENT)!=SQLITE_OK) Fail("trusted_store_bind_failed"); }
    std::string Text(int n) const {const auto* p=sqlite3_column_text(s,n);return p?reinterpret_cast<const char*>(p):"";}
    int Step() { return sqlite3_step(s); }
};
bool Contains(const Json& values,const Json& v) {return std::find(values.begin(),values.end(),v)!=values.end();}
void Identity(const Json& v) {
    if(!v.is_string()) Fail("invalid_identifier");
    auto s=v.get<std::string>();
    if(s.empty() || s.size()>2048 || std::any_of(s.begin(),s.end(),[](unsigned char c){return c<32;})) Fail("invalid_identifier");
}
}
double Now() {return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();}
std::string Digest(std::string_view data) {
    std::array<unsigned char,32> result{}; unsigned size=0;
    if(EVP_Digest(data.data(),data.size(),result.data(),&size,EVP_sha256(),nullptr)!=1) Fail("digest_failed");
    return Hex(result.data(),size);
}
std::string Hmac(std::string_view key,std::string_view data) {
    std::array<unsigned char,32> result{};unsigned size=0;
    if(!HMAC(EVP_sha256(),key.data(),int(key.size()),reinterpret_cast<const unsigned char*>(data.data()),data.size(),result.data(),&size)) Fail("hmac_failed");
    return Hex(result.data(),size);
}
bool ConstantEqual(std::string_view a,std::string_view b) {
    return a.size()==b.size() && CRYPTO_memcmp(a.data(),b.data(),a.size())==0;
}
std::string RandomId() {
    std::array<unsigned char,16> b{};if(RAND_bytes(b.data(),int(b.size()))!=1) Fail("entropy_unavailable");
    return Hex(b.data(),b.size());
}
std::string Encrypt(std::string_view key,std::string_view data,std::string_view binding) {
    if(key.size()!=32 || data.size()>MaximumFrameBytes) Fail("invalid_encryption_input");
    std::array<unsigned char,12> nonce{}; if(RAND_bytes(nonce.data(),12)!=1) Fail("entropy_unavailable");
    std::unique_ptr<EVP_CIPHER_CTX,decltype(&EVP_CIPHER_CTX_free)> ctx(EVP_CIPHER_CTX_new(),EVP_CIPHER_CTX_free);
    std::string result(12+data.size()+16,'\0'); int count=0,total=0;
    std::copy(nonce.begin(),nonce.end(),result.begin());
    if(!ctx || EVP_EncryptInit_ex(ctx.get(),EVP_aes_256_gcm(),nullptr,reinterpret_cast<const unsigned char*>(key.data()),nonce.data())!=1 ||
       EVP_EncryptUpdate(ctx.get(),nullptr,&count,reinterpret_cast<const unsigned char*>(binding.data()),int(binding.size()))!=1 ||
       EVP_EncryptUpdate(ctx.get(),reinterpret_cast<unsigned char*>(result.data()+12),&count,reinterpret_cast<const unsigned char*>(data.data()),int(data.size()))!=1) Fail("encryption_failed");
    total=count;
    if(EVP_EncryptFinal_ex(ctx.get(),reinterpret_cast<unsigned char*>(result.data()+12+total),&count)!=1 ||
       EVP_CIPHER_CTX_ctrl(ctx.get(),EVP_CTRL_GCM_GET_TAG,16,result.data()+12+data.size())!=1) Fail("encryption_failed");
    return result;
}
std::string Decrypt(std::string_view key,std::string_view data,std::string_view binding) {
    if(key.size()!=32 || data.size()<28 || data.size()>MaximumFrameBytes+28) Fail("invalid_encrypted_record");
    std::unique_ptr<EVP_CIPHER_CTX,decltype(&EVP_CIPHER_CTX_free)> ctx(EVP_CIPHER_CTX_new(),EVP_CIPHER_CTX_free);
    std::string result(data.size()-28,'\0'); int count=0,total=0;
    if(!ctx || EVP_DecryptInit_ex(ctx.get(),EVP_aes_256_gcm(),nullptr,reinterpret_cast<const unsigned char*>(key.data()),reinterpret_cast<const unsigned char*>(data.data()))!=1 ||
       EVP_DecryptUpdate(ctx.get(),nullptr,&count,reinterpret_cast<const unsigned char*>(binding.data()),int(binding.size()))!=1 ||
       EVP_DecryptUpdate(ctx.get(),reinterpret_cast<unsigned char*>(result.data()),&count,reinterpret_cast<const unsigned char*>(data.data()+12),int(result.size()))!=1) Fail("encrypted_record_invalid");
    total=count;
    if(EVP_CIPHER_CTX_ctrl(ctx.get(),EVP_CTRL_GCM_SET_TAG,16,const_cast<char*>(data.data()+data.size()-16))!=1 ||
       EVP_DecryptFinal_ex(ctx.get(),reinterpret_cast<unsigned char*>(result.data()+total),&count)!=1) {
        OPENSSL_cleanse(result.data(),result.size());Fail("encrypted_record_invalid");
    }
    return result;
}
void ValidateAction(const Json& a) {
    if(!a.is_object() || a.dump().size()>MaximumFrameBytes/2 || !a.at("payload").is_object()) Fail("invalid_action");
    if(!a.at("sources").is_array()||a.at("sources").size()>200)Fail("provenance_budget_exhausted");
    for(auto k:{"principal","operation","purpose","destination","workflow","execution_id"}) Identity(a.at(k));
    for(auto k:{"platform","account_id","conversation_id"}) Identity(a.at("resource").at(k));
    for(const auto& source:a.at("sources")) {
        if(source.at("trust")!="untrusted-external") Fail("external_data_cannot_be_trusted");
        Identity(source.at("reference"));
        for(auto k:{"platform","account_id","conversation_id"}) Identity(source.at("resource").at(k));
        if(!Contains(Json{"workspace-normal","personal","sensitive","credentials","financial"},source.at("data_class"))) Fail("invalid_data_class");
    }
}
std::string IntentSeal(const Json& a) {ValidateAction(a);return Digest(Json{{"version",ProtocolVersion},{"intent",a}}.dump());}
unsigned Risk(const Json& a) {
    auto op=a.at("operation").get<std::string>();
    for(const auto& p:a.at("sources")) if(Contains(Json{"sensitive","credentials","financial"},p.at("data_class")))return 4;
    if(op.starts_with("funds.")||op.starts_with("credentials."))return 4;
    if(op.starts_with("messages.send")||op.starts_with("files.delete")||op.starts_with("disclosure."))return 3;
    return (op=="messages.read"||op=="messages.search"||op=="files.read"||op=="status.read")?1:2;
}
bool Terminal(std::string_view s) {return s=="Completed"||s=="Unknown"||s=="Denied"||s=="Expired"||s=="Cancelled"||s=="FailedSafe";}
bool ValidTransition(std::string_view from,std::string_view to) {
    static const std::map<std::string,std::set<std::string>> edges{
        {"Proposed",{"PolicyChecked","Denied","Cancelled"}},
        {"PolicyChecked",{"Ready","AwaitingApproval","Denied","Cancelled"}},
        {"AwaitingApproval",{"Ready","Denied","Expired","Cancelled"}},
        {"Ready",{"Prepared","Denied","Expired","Cancelled","FailedSafe"}},
        {"Prepared",{"Executing","Cancelled","FailedSafe"}},
        {"Executing",{"Verifying","Unknown","FailedSafe"}},
        {"Verifying",{"Completed","Unknown","FailedSafe"}}};
    auto it=edges.find(std::string(from));return it!=edges.end()&&it->second.contains(std::string(to));
}
struct Guard::Impl {
    sqlite3* db{};std::string key;
    ~Impl(){if(db)sqlite3_close(db);OPENSSL_cleanse(key.data(),key.size());}
    unsigned Version() const {Statement q(db,"SELECT version FROM policy");if(q.Step()!=SQLITE_ROW)Fail("policy_missing");return unsigned(sqlite3_column_int(q.s,0));}
    std::string Find(const Json& a,double now,bool quota,const std::string& id="",const std::string& requiredClass="") const {
        Statement q(db,id.empty()?"SELECT id,body,signature,used,revoked FROM grants":"SELECT id,body,signature,used,revoked FROM grants WHERE id=?");
        if(!id.empty())q.Text(1,id);
        while(q.Step()==SQLITE_ROW) {
            auto b=Json::parse(q.Text(1));
            if(!ConstantEqual(q.Text(2),Hmac(key,b.dump())))Fail("grant_integrity_failed");
            if(sqlite3_column_int(q.s,4)|| b.at("expires_at").get<double>()<=now ||
               (quota&&sqlite3_column_int(q.s,3)>=b.at("max_uses").get<int>())||
               b.at("policy_version")!=Version()||b.at("principal")!=a.at("principal")||
               b.at("resource")!=a.at("resource")||!Contains(b.at("operations"),a.at("operation"))||
               b.at("purpose")!=a.at("purpose")||b.at("workflow")!=a.at("workflow")||
               (!b.at("intent").is_null()&&b.at("intent")!=IntentSeal(a))||
               (a.at("operation")=="application.navigate"&&
                (b.at("intent")!=IntentSeal(a)||b.at("max_uses")!=1||b.at("expires_at").get<double>()-now>300))||
               (a.at("destination")!="local"&&!Contains(b.at("destinations"),a.at("destination")))||
               (Risk(a)==4&&b.at("intent")!=IntentSeal(a))||
               (!requiredClass.empty()&&!Contains(b.at("classes"),requiredClass))) continue;
            bool valid=true;for(const auto& p:a.at("sources"))valid=valid&&Contains(b.at("classes"),p.at("data_class"));
            if(valid)return q.Text(0);
        }
        Fail("authority_missing_expired_revoked_or_exhausted");
    }
    std::vector<std::string> Sources(const Json& a,double now) const {
        std::vector<std::string> ids;
        for(const auto& p:a.at("sources")) {
            // A read's own classified query is covered by its primary grant.
            // Requiring a second empty-payload grant would reject exact sensitive
            // approvals and the last allowed page after primary quota consumption.
            if(Contains(Json{"messages.read","messages.search"},a.at("operation"))&&
               p.at("resource")==a.at("resource"))continue;
            auto access=a;access["resource"]=p.at("resource");access["sources"]=Json::array();
            access["operation"]="messages.read";access["payload"]=Json::object();access["destination"]="local";
            ids.push_back(Find(access,now,true,"",p.at("data_class").get<std::string>()));
            if(a.at("destination")!="local") {
                access["operation"]="disclosure.send";access["payload"]={{"output_seal",IntentSeal(a)}};
                access["destination"]=a.at("destination");access["sources"]=Json::array({p});
                ids.push_back(Find(access,now,true));
            }
        }
        return ids;
    }
};
Guard::Guard(const std::filesystem::path& path,std::string key):impl_(std::make_unique<Impl>()) {
    if(key.size()!=32)Fail("invalid_guard_key");impl_->key=std::move(key);
    auto utf8=path.u8string();
    if(sqlite3_open_v2(reinterpret_cast<const char*>(utf8.c_str()),&impl_->db,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_FULLMUTEX,nullptr)!=SQLITE_OK)Fail("trusted_store_unavailable");
    sqlite3_busy_timeout(impl_->db,5000);
    Exec(impl_->db,"PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;CREATE TABLE IF NOT EXISTS policy(version INTEGER NOT NULL);INSERT INTO policy SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM policy);CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY,body TEXT NOT NULL,signature TEXT NOT NULL,used INTEGER NOT NULL DEFAULT 0,revoked INTEGER NOT NULL DEFAULT 0);");
}
Guard::~Guard()=default;
unsigned Guard::Version() const {return impl_->Version();}
std::string Guard::IssueOwner(Json b,double now) {
    auto expiry=b.at("expires_at").get<double>();
    if(!std::isfinite(expiry)||expiry-now<1||expiry-now>86400*30||!b.at("max_uses").is_number_integer()||
       b.at("max_uses").get<int>()<1||b.at("max_uses").get<int>()>100000||b.at("operations").empty())Fail("invalid_grant");
    for(const auto& op:b.at("operations")) {
        Identity(op);auto s=op.get<std::string>();
        if((s=="application.navigate"||s.starts_with("messages.send")||s.starts_with("disclosure.")||s.starts_with("files.delete")||s.starts_with("funds.")||s.starts_with("credentials."))&&b.at("intent").is_null())Fail("external_action_requires_exact_intent");
    }
    if(!b.at("intent").is_null()&&(expiry-now>300||b.at("max_uses")!=1))Fail("one_action_grant_requires_short_expiry");
    b["id"]=RandomId();b["policy_version"]=Version();
    auto text=b.dump();Statement q(impl_->db,"INSERT INTO grants(id,body,signature) VALUES(?,?,?)");
    q.Text(1,b.at("id").get<std::string>());q.Text(2,text);q.Text(3,Hmac(impl_->key,text));
    if(q.Step()!=SQLITE_DONE)Fail("grant_store_failed");return b.at("id").get<std::string>();
}
void Guard::RevokeOwner(const std::string& id) {
    Exec(impl_->db,"BEGIN IMMEDIATE");
    try{Statement q(impl_->db,"UPDATE grants SET revoked=1 WHERE id=?");q.Text(1,id);if(q.Step()!=SQLITE_DONE)Fail("revocation_failed");Exec(impl_->db,"UPDATE policy SET version=version+1;COMMIT;");}
    catch(...){Exec(impl_->db,"ROLLBACK");throw;}
}
std::string Guard::Check(const Json& a,double now,bool quota) const {ValidateAction(a);impl_->Sources(a,now);return impl_->Find(a,now,quota);}
Json Guard::Consume(const Json& a,double now) {
    Exec(impl_->db,"BEGIN IMMEDIATE");
    try{auto id=Check(a,now);Statement q(impl_->db,"UPDATE grants SET used=used+1 WHERE id=?");q.Text(1,id);if(q.Step()!=SQLITE_DONE)Fail("quota_update_failed");auto v=Version();Exec(impl_->db,"COMMIT");return Json::array({id,v});}
    catch(...){Exec(impl_->db,"ROLLBACK");throw;}
}
Json Guard::ExecutionProof(const Json& a,const std::string& id,unsigned version,double now) const {
    Revalidate(a,id,version,now);
    Json grants=Json::array();
    auto descriptor=[&](const std::string& grant,bool quota){
        Statement q(impl_->db,"SELECT body FROM grants WHERE id=?");q.Text(1,grant);
        if(q.Step()!=SQLITE_ROW)Fail("grant_missing_before_commit");
        return Json{{"id",grant},{"body_sha256",Digest(q.Text(0))},{"require_quota",quota}};
    };
    grants.push_back(descriptor(id,false));
    for(const auto& source:impl_->Sources(a,now))grants.push_back(descriptor(source,true));
    return {{"version",1},{"policy_version",version},{"intent_seal",IntentSeal(a)},{"action",a},{"grants",grants}};
}
void Guard::Revalidate(const Json& a,const std::string& id,unsigned version,double now) const {
    ValidateAction(a);if(version!=Version())Fail("policy_changed_before_commit");impl_->Sources(a,now);impl_->Find(a,now,false,id);
}
}

extern "C" int axr_check_commit(const char* path,const char* encoded) {
    using namespace Stellaria::AXR;sqlite3* db=nullptr;
    try {
        if(!path||!encoded||std::char_traits<char>::length(encoded)>MaximumFrameBytes)return 0;
        auto proof=Json::parse(encoded);
        if(proof.at("version")!=1||proof.at("grants").empty()||proof.at("grants").size()>401)return 0;
        const auto& action=proof.at("action");ValidateAction(action);
        if(proof.at("intent_seal")!=IntentSeal(action))return 0;
        std::vector<std::pair<Json,std::string>> expected{{action,""}};
        for(const auto& source:action.at("sources")) {
            if(Contains(Json{"messages.read","messages.search"},action.at("operation"))&&source.at("resource")==action.at("resource"))continue;
            auto access=action;access["resource"]=source.at("resource");access["sources"]=Json::array();
            access["operation"]="messages.read";access["payload"]=Json::object();access["destination"]="local";
            expected.emplace_back(access,source.at("data_class").get<std::string>());
            if(action.at("destination")!="local") {
                access["operation"]="disclosure.send";access["payload"]={{"output_seal",IntentSeal(action)}};
                access["destination"]=action.at("destination");access["sources"]=Json::array({source});
                expected.emplace_back(access,source.at("data_class").get<std::string>());
            }
        }
        if(proof.at("grants").size()!=expected.size())return 0;
        if(sqlite3_open_v2(path,&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_FULLMUTEX,nullptr)!=SQLITE_OK){if(db)sqlite3_close(db);return 0;}
        sqlite3_busy_timeout(db,1000);
        bool valid=true;
        {
            Statement version(db,"SELECT version FROM policy");
            valid=version.Step()==SQLITE_ROW&&sqlite3_column_int(version.s,0)==proof.at("policy_version").get<int>();
            std::size_t descriptorIndex=0;
            for(const auto& descriptor:proof.at("grants")) {
                Statement grant(db,"SELECT body,used,revoked FROM grants WHERE id=?");grant.Text(1,descriptor.at("id").get<std::string>());
                if(grant.Step()!=SQLITE_ROW){valid=false;break;}
                auto body=grant.Text(0);auto parsed=Json::parse(body);
                const auto& [requested,requiredClass]=expected[descriptorIndex];
                {
                    valid=valid&&descriptor.at("require_quota")==Json(descriptorIndex!=0);
                    valid=valid&&parsed.at("policy_version")==proof.at("policy_version")&&
                        parsed.at("principal")==requested.at("principal")&&parsed.at("resource")==requested.at("resource")&&
                        parsed.at("purpose")==requested.at("purpose")&&parsed.at("workflow")==requested.at("workflow")&&
                        Contains(parsed.at("operations"),requested.at("operation"))&&
                        (parsed.at("intent").is_null()||parsed.at("intent")==IntentSeal(requested))&&
                        (requested.at("operation")!="application.navigate"||
                         (parsed.at("intent")==IntentSeal(requested)&&parsed.at("max_uses")==1&&parsed.at("expires_at").get<double>()-Now()<=300))&&
                        (requested.at("destination")=="local"||Contains(parsed.at("destinations"),requested.at("destination")))&&
                        (requiredClass.empty()||Contains(parsed.at("classes"),requiredClass));
                    for(const auto& source:requested.at("sources"))valid=valid&&Contains(parsed.at("classes"),source.at("data_class"));
                }
                ++descriptorIndex;
                valid=valid&&ConstantEqual(Digest(body),descriptor.at("body_sha256").get<std::string>())&&
                    !sqlite3_column_int(grant.s,2)&&parsed.at("expires_at").get<double>()>Now()&&
                    (!descriptor.at("require_quota").get<bool>()||sqlite3_column_int(grant.s,1)<parsed.at("max_uses").get<int>());
            }
        }
        // The previous active statements share a read snapshot. End that snapshot
        // before checking the latest policy version, so a concurrent owner revoke
        // is observed before the helper proceeds to its platform commit.
        {
            Statement latest(db,"SELECT version FROM policy");
            valid=valid&&latest.Step()==SQLITE_ROW&&sqlite3_column_int(latest.s,0)==proof.at("policy_version").get<int>();
        }
        sqlite3_close(db);db=nullptr;return valid?1:0;
    }catch(...){if(db)sqlite3_close(db);return 0;}
}

extern "C" int axr_check_scoped_commit(const char* path,const char* encoded,const char* scopeEncoded) {
    using namespace Stellaria::AXR;
    try {
        if(!scopeEncoded||std::char_traits<char>::length(scopeEncoded)>MaximumFrameBytes)return 0;
        auto scope=Json::parse(scopeEncoded);
        if(!axr_check_commit(path,encoded))return 0;
        const auto action=Json::parse(encoded).at("action");
        if(scope.at("resource")!=action.at("resource")||
           !Contains(scope.at("operations"),action.at("operation")))return 0;
        if(scope.contains("text")&&scope.at("text")!=action.at("payload").at("text"))return 0;
        if(scope.contains("visual_binding")&&scope.at("visual_binding")!=action.at("payload").at("visual_binding"))return 0;
        // Navigation is a side effect. A resource-only proof cannot authorize
        // a substituted process, menu command or verification window.
        if(action.at("operation")=="application.navigate" &&
           (!scope.contains("navigation_binding") ||
            scope.at("navigation_binding")!=action.at("payload").at("navigation_binding")))return 0;
        return 1;
    }catch(...){return 0;}
}
