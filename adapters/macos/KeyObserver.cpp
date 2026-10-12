// SPDX-License-Identifier: MIT
// Optional owner-only startup observation on a temporary application copy.
// Forward Apple's original KDF unchanged. No attach, patch, key stdout or file.
#include <CommonCrypto/CommonKeyDerivation.h>
#include <dlfcn.h>
#include <pthread.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <atomic>
#include <cstring>
#include <cstdlib>
#include <cstdint>

using Function=int(*)(CCPBKDFAlgorithm,const char*,size_t,const uint8_t*,size_t,
                     CCPseudoRandomAlgorithm,uint,uint8_t*,size_t);
static Function original=nullptr;
static pthread_once_t once=PTHREAD_ONCE_INIT;
static std::atomic<unsigned> sent{0};
static int observe(CCPBKDFAlgorithm,const char*,size_t,const uint8_t*,size_t,
                   CCPseudoRandomAlgorithm,uint,uint8_t*,size_t);
static void resolveOriginal() {
    // dyld excludes references originating in the interposing image itself.
    auto address=reinterpret_cast<void*>(&CCKeyDerivationPBKDF);
    Dl_info info{};
    if(address!=reinterpret_cast<void*>(&observe) && dladdr(address,&info) &&
       info.dli_fname && !std::strcmp(info.dli_fname,"/usr/lib/system/libcommonCrypto.dylib"))
        std::memcpy(&original,&address,sizeof(original));
}
static int observe(CCPBKDFAlgorithm algorithm,const char* password,size_t plen,
                   const uint8_t* salt,size_t slen,CCPseudoRandomAlgorithm prf,
                   uint rounds,uint8_t* output,size_t olen) {
    if(pthread_once(&once,resolveOriginal) || !original) _exit(127);
    const int result=original(algorithm,password,plen,salt,slen,prf,rounds,output,olen);
    if(result==0 && algorithm==kCCPBKDF2 && password && plen>0 && plen<=256 &&
       salt && slen==16 && prf==kCCPRFHmacAlgSHA512 && rounds==256000 && output &&
       olen==32 && sent.fetch_add(1,std::memory_order_relaxed)<128) {
        const char* path=std::getenv("AXR_OWNER_KEY_FIFO");
        if(path && path[0]=='/') {
            int fd=open(path,O_WRONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
            if(fd>=0) {
                struct stat st{};
                if(!fstat(fd,&st) && S_ISFIFO(st.st_mode) && st.st_uid==getuid() &&
                   (st.st_mode&0777)==0600) {
                    unsigned char record[52];
                    std::memcpy(record,"AXK1",4);std::memcpy(record+4,salt,16);
                    std::memcpy(record+20,output,32);
                    (void)write(fd,record,sizeof(record)); // <= PIPE_BUF; never blocks.
                    for(volatile unsigned char* p=record;p!=record+sizeof(record);++p)*p=0;
                }
                close(fd);
            }
        }
    }
    return result;
}
__attribute__((used)) static struct {const void* replacement;const void* target;}
interpose __attribute__((section("__DATA,__interpose")))={
    reinterpret_cast<const void*>(&observe),reinterpret_cast<const void*>(&CCKeyDerivationPBKDF)};
