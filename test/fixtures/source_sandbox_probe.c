// SPDX-License-Identifier: MIT
// Synthetic process used only to witness the source provider's OS boundaries.
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
int main(int argc,char** argv){
    if(argc==3&&!strcmp(argv[1],"read")){
        FILE* file=fopen(argv[2],"rb");printf("%s\n",file?"allowed":"denied");if(file)fclose(file);return 0;
    }
    if(argc==2&&!strcmp(argv[1],"exec")){
        pid_t pid=fork();if(pid<0)return 2;
        if(!pid){execl("/usr/bin/true","true",(char*)0);_exit(127);}
        int status=0;if(waitpid(pid,&status,0)<0)return 2;
        printf("%s\n",WIFEXITED(status)&&WEXITSTATUS(status)==0?"allowed":"denied");return 0;
    }
    return 2;
}
