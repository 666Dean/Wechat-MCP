// SPDX-License-Identifier: MIT
// Synthetic known input. Does not load WeChat or an owner database.
#include <CommonCrypto/CommonKeyDerivation.h>
#include <cstdio>
#include <cstring>
int main(int argc,char** argv) {
    const char password[]="synthetic-observer-fixture";
    unsigned char salt[16],key[32];std::memset(salt,0x61,sizeof(salt));
    unsigned rounds=(argc>1 && !std::strcmp(argv[1],"unmatched")) ? 1 : 256000;
    int status=CCKeyDerivationPBKDF(kCCPBKDF2,password,sizeof(password)-1,salt,sizeof(salt),
                                  kCCPRFHmacAlgSHA512,rounds,key,sizeof(key));
    if(status)return 1;
    for(auto value:key)std::printf("%02x",value);
    std::puts("");return 0;
}
