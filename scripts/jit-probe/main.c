// iOS JIT-memory probe executable v3 (arm64-apple-ios), diagnostic only.
// Each test runs in its own process (argv[1] = A..F, or "all" to print usage)
// so a SIGBUS in one test cannot hide the results of the others.
// Signed twice by CI: 2-key and JIT-keys entitlement sets.
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_JIT
#define MAP_JIT 0x800
#endif

static const unsigned char kRet[] = {0xC0, 0x03, 0x5F, 0xD6};  // ret
static const size_t kPage = 16384;

static void exec_stub(void *p) {
  int (*fn)(void) = (int (*)(void))p;
  fn();
}

static void report(const char *name, int rc, int err) {
  printf("%s rc=%d errno=%d\n", name, rc, err);
  fflush(stdout);
}

int main(int argc, char **argv) {
  setvbuf(stdout, NULL, _IONBF, 0);
  if (argc < 2) {
    printf("usage: %s A|B|C|D|E|F\n", argv[0]);
    return 2;
  }
  const char t = argv[1][0];
  int rc = -1, err = 0;
  const int prot_rwx = PROT_READ | PROT_WRITE | PROT_EXEC;
  const int prot_rw = PROT_READ | PROT_WRITE;
  const int prot_rx = PROT_READ | PROT_EXEC;

  if (t == 'A') {  // plain RWX mmap, write, execute
    void *p = mmap(NULL, kPage, prot_rwx, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { err = errno; report("A_plain_mmap_rwx", -1, err); return 1; }
    memcpy(p, kRet, sizeof kRet);
    err = errno;
    report("A_plain_mmap_rwx_pre_exec", 0, err);
    exec_stub(p);
    report("A_plain_mmap_rwx_exec", 0, 0);
  } else if (t == 'B') {  // MAP_JIT RWX mmap, write, execute
    void *p = mmap(NULL, kPage, prot_rwx, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
    if (p == MAP_FAILED) { err = errno; report("B_mapjit_mmap_rwx", -1, err); return 1; }
    memcpy(p, kRet, sizeof kRet);
    report("B_mapjit_mmap_rwx_pre_exec", 0, errno);
    exec_stub(p);
    report("B_mapjit_mmap_rwx_exec", 0, 0);
  } else if (t == 'C') {  // MAP_JIT PROT_NONE -> mprotect RWX -> write -> exec
    void *p = mmap(NULL, kPage, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
    if (p == MAP_FAILED) { report("C_mapjit_reserve", -1, errno); return 1; }
    rc = mprotect(p, kPage, prot_rwx);
    report("C_mapjit_mprotect_rwx", rc, rc ? errno : 0);
    if (rc) return 1;
    memcpy(p, kRet, sizeof kRet);
    exec_stub(p);
    report("C_mapjit_rwx_exec", 0, 0);
  } else if (t == 'D') {  // plain PROT_NONE -> mprotect RWX -> write -> exec
    void *p = mmap(NULL, kPage, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { report("D_plain_reserve", -1, errno); return 1; }
    rc = mprotect(p, kPage, prot_rwx);
    report("D_plain_mprotect_rwx", rc, rc ? errno : 0);
    if (rc) return 1;
    memcpy(p, kRet, sizeof kRet);
    exec_stub(p);
    report("D_plain_rwx_exec", 0, 0);
  } else if (t == 'E') {  // plain RW -> write -> mprotect RX -> exec
    void *p = mmap(NULL, kPage, prot_rw, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { report("E_plain_rw", -1, errno); return 1; }
    memcpy(p, kRet, sizeof kRet);
    rc = mprotect(p, kPage, prot_rx);
    report("E_plain_mprotect_rx", rc, rc ? errno : 0);
    if (rc) return 1;
    exec_stub(p);
    report("E_plain_rx_exec", 0, 0);
  } else if (t == 'F') {  // MAP_JIT RW -> write -> mprotect RX -> exec
    void *p = mmap(NULL, kPage, prot_rw, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
    if (p == MAP_FAILED) { report("F_mapjit_rw", -1, errno); return 1; }
    memcpy(p, kRet, sizeof kRet);
    rc = mprotect(p, kPage, prot_rx);
    report("F_mapjit_mprotect_rx", rc, rc ? errno : 0);
    if (rc) return 1;
    exec_stub(p);
    report("F_mapjit_rx_exec", 0, 0);
  } else if (t == 'G') {  // MAP_JIT RWX then mprotect RWX again (V8 v4 path)
    void *p = mmap(NULL, kPage, prot_rwx, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
    if (p == MAP_FAILED) { report("G_mapjit_rwx", -1, errno); return 1; }
    rc = mprotect(p, kPage, prot_rwx);
    report("G_mapjit_remprotect_rwx", rc, rc ? errno : 0);
    if (rc) return 1;
    memcpy(p, kRet, sizeof kRet);
    exec_stub(p);
    report("G_mapjit_remprotect_rwx_exec", 0, 0);
  } else if (t == 'H') {  // plain RWX then mprotect RWX again
    void *p = mmap(NULL, kPage, prot_rwx, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { report("H_plain_rwx", -1, errno); return 1; }
    rc = mprotect(p, kPage, prot_rwx);
    report("H_plain_remprotect_rwx", rc, rc ? errno : 0);
    if (rc) return 1;
    memcpy(p, kRet, sizeof kRet);
    exec_stub(p);
    report("H_plain_remprotect_rwx_exec", 0, 0);
  } else {
    printf("unknown test %c\n", t);
    return 2;
  }

  void *sym = dlsym(RTLD_DEFAULT, "pthread_jit_write_protect_np");
  printf("pthread_jit_write_protect_np: %s uid=%d\n", sym ? "present" : "absent", (int)getuid());
  return 0;
}
