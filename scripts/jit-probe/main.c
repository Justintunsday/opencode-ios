// iOS JIT-memory probe executable (arm64-apple-ios), ldid-signed with the same
// entitlement set the shipped runtime uses. Diagnostic only.
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_JIT
#define MAP_JIT 0x800
#endif

int main(void) {
  const size_t page = 16384;
  printf("jit-probe uid=%d page=%zu\n", (int)getuid(), page);

  // 1. plain PROT_NONE then mprotect RWX
  void *p1 = mmap(NULL, page, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int rc1 = (p1 == MAP_FAILED) ? -1 : mprotect(p1, page, PROT_READ | PROT_WRITE | PROT_EXEC);
  printf("plain_then_mprotect_rwx: mmap=%s mprotect=%d errno=%d\n", p1 == MAP_FAILED ? "FAIL" : "ok",
         rc1, rc1 == 0 ? 0 : errno);

  // 2. MAP_JIT mmap RWX directly
  void *p2 = mmap(NULL, page, PROT_READ | PROT_WRITE | PROT_EXEC,
                  MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
  printf("mmap_jit_rwx: %s errno=%d\n", p2 == MAP_FAILED ? "FAIL" : "ok", p2 == MAP_FAILED ? errno : 0);

  // 3. plain write then mprotect RX then execute a `ret` stub
  void *p3 = mmap(NULL, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int rc3 = -1, exec_ok = -1;
  if (p3 != MAP_FAILED) {
    unsigned char stub[] = {0xC0, 0x03, 0x5F, 0xD6};  // ret
    memcpy(p3, stub, sizeof stub);
    rc3 = mprotect(p3, page, PROT_READ | PROT_EXEC);
    if (rc3 == 0) {
      int (*fn)(void) = (int (*)(void))p3;
      fn();
      exec_ok = 0;
    }
  }
  printf("plain_write_rx_exec: mprotect_rx=%d exec=%d errno=%d\n", rc3, exec_ok, rc3 == 0 ? 0 : errno);

  // 4. MAP_JIT reservation then RWX then execute
  void *p4 = mmap(NULL, page, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
  int rc4 = -1, exec4 = -1;
  if (p4 != MAP_FAILED) {
    rc4 = mprotect(p4, page, PROT_READ | PROT_WRITE | PROT_EXEC);
    if (rc4 == 0) {
      unsigned char stub[] = {0xC0, 0x03, 0x5F, 0xD6};
      memcpy(p4, stub, sizeof stub);
      int (*fn)(void) = (int (*)(void))p4;
      fn();
      exec4 = 0;
    }
  }
  printf("mapjit_reserve_mprotect_rwx_exec: mprotect=%d exec=%d errno=%d\n", rc4, exec4,
         rc4 == 0 ? 0 : errno);

  // 5. pthread_jit_write_protect_np availability
  void *sym = dlsym(RTLD_DEFAULT, "pthread_jit_write_protect_np");
  printf("pthread_jit_write_protect_np: %s\n", sym ? "present" : "absent");

  printf("JIT_PROBE_DONE\n");
  return 0;
}
