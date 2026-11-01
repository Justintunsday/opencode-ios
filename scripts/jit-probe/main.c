// iOS JIT-memory probe executable v2 (arm64-apple-ios).
// Determines which executable-memory strategy can actually host V8's JIT on the
// target device. Runs the same tests for two signatures (2-key and JIT-keys) so
// the caller can compare entitlement effects. Diagnostic only.
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

static int can_exec_rw(void *p) {
  if (p == MAP_FAILED) return -1;
  memcpy(p, kRet, sizeof kRet);
  int (*fn)(void) = (int (*)(void))p;
  fn();
  return 0;
}

static int can_exec_rx(void *p, size_t page) {
  if (p == MAP_FAILED) return -1;
  if (mprotect(p, page, PROT_READ | PROT_EXEC) != 0) return -1;
  int (*fn)(void) = (int (*)(void))p;
  fn();
  return 0;
}

int main(void) {
  const size_t page = 16384;
  printf("jit-probe-v2 uid=%d pid=%d page=%zu\n", (int)getuid(), (int)getpid(), page);

  // A. plain mapping created RWX directly, write + execute
  void *a = mmap(NULL, page, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANON, -1, 0);
  printf("A_plain_mmap_rwx_exec: mmap=%s exec=%d errno=%d\n", a == MAP_FAILED ? "FAIL" : "ok",
         can_exec_rw(a), a == MAP_FAILED ? errno : 0);

  // B. MAP_JIT mapping created RWX directly (no APRR toggling), write + execute
  void *b = mmap(NULL, page, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
  printf("B_mapjit_mmap_rwx_exec: mmap=%s exec=%d errno=%d\n", b == MAP_FAILED ? "FAIL" : "ok",
         can_exec_rw(b), b == MAP_FAILED ? errno : 0);

  // C. MAP_JIT reservation (no access) then mprotect RWX, write + execute
  void *c = mmap(NULL, page, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
  int rc_c = -1, exec_c = -1;
  if (c != MAP_FAILED) {
    rc_c = mprotect(c, page, PROT_READ | PROT_WRITE | PROT_EXEC);
    if (rc_c == 0) exec_c = can_exec_rw(c);
  }
  printf("C_mapjit_reserve_mprotect_rwx_exec: mmap=%s mprotect=%d exec=%d errno=%d\n",
         c == MAP_FAILED ? "FAIL" : "ok", rc_c, exec_c, c == MAP_FAILED ? errno : 0);

  // D. plain PROT_NONE then mprotect RWX, write + execute (v5/V8 assumption)
  void *d = mmap(NULL, page, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int rc_d = -1, exec_d = -1;
  if (d != MAP_FAILED) {
    rc_d = mprotect(d, page, PROT_READ | PROT_WRITE | PROT_EXEC);
    if (rc_d == 0) exec_d = can_exec_rw(d);
  }
  printf("D_plain_reserve_mprotect_rwx_exec: mmap=%s mprotect=%d exec=%d errno=%d\n",
         d == MAP_FAILED ? "FAIL" : "ok", rc_d, exec_d, d == MAP_FAILED ? errno : 0);

  // E. plain RW then mprotect RX, execute (the W^X pattern V8 must use)
  void *e = mmap(NULL, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int exec_e = -1;
  if (e != MAP_FAILED) {
    memcpy(e, kRet, sizeof kRet);
    exec_e = can_exec_rx(e, page);
  }
  printf("E_plain_rw_mprotect_rx_exec: mmap=%s exec=%d errno=%d\n", e == MAP_FAILED ? "FAIL" : "ok",
         exec_e, e == MAP_FAILED ? errno : 0);

  // F. MAP_JIT RW then mprotect RX, execute
  void *f = mmap(NULL, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
  int exec_f = -1;
  if (f != MAP_FAILED) {
    memcpy(f, kRet, sizeof kRet);
    exec_f = can_exec_rx(f, page);
  }
  printf("F_mapjit_rw_mprotect_rx_exec: mmap=%s exec=%d errno=%d\n", f == MAP_FAILED ? "FAIL" : "ok",
         exec_f, f == MAP_FAILED ? errno : 0);

  void *sym = dlsym(RTLD_DEFAULT, "pthread_jit_write_protect_np");
  printf("pthread_jit_write_protect_np: %s\n", sym ? "present" : "absent");
  printf("JIT_PROBE_DONE\n");
  return 0;
}
