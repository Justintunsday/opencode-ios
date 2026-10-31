#include <stdio.h>
#include <sys/utsname.h>
#include <unistd.h>

int main(void) {
    struct utsname info;
    if (uname(&info) != 0) {
        perror("uname");
        return 1;
    }
    printf("IOS_ROOTLESS_PORT_SMOKE_OK\n");
    printf("system=%s machine=%s uid=%ld\n", info.sysname, info.machine, (long)getuid());
    return 0;
}
