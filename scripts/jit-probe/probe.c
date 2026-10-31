// iOS JIT-memory probe dylib (arm64-apple-ios), injected via DYLD_INSERT_LIBRARIES.
// Purpose: determine, on a jailbroken iOS 16 device, which executable-memory
// primitives are permitted to an ldid-signed CLI process:
//   1. plain mmap(PROT_NONE) then mprotect(PROT_READ|PROT_WRITE|PROT_EXEC)
//   2. mmap(MAP_JIT, PROT_READ|PROT_WRITE|PROT_EXEC)  (MAP_JIT = 0x800)
//   3. mprotect(PROT_READ|PROT_EXEC) after writing code (W^X toggle)
//   4. availability of pthread_jit_write_protect_np via dlsym
// Results are appended to /var/mobile/jit-probe-result.txt so the caller can
// read them after the injected process exits.
#include <dlfcn.h>
#include <fcntl.h>
#include <mach/mach.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_JIT
#define MAP_JIT 0x800
#endif

static void append(const char *line) {
  int fd = open("/var/mobile/jit-probe-result.txt", O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd < 0) return;
  write(fd, line, strlen(line));
  close(fd);
}

__attribute__((constructor)) static void probe(void) {
  char buf[512];
  int fd = open("/var/mobile/jit-probe-result.txt", O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd >= 0) {
    snprintf(buf, sizeof buf, "== jit-probe pid=%d uid=%d ==\n", (int)getpid(), (int)getuid());
    write(fd, buf, strlen(buf));
    close(fd);
  }

  const size_t page = 16384;
  // 1. plain PROT_NONE reservation then mprotect RWX
  void *p1 = mmap(NULL, page, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int rc1 = (p1 == MAP_FAILED) ? -1 : mprotect(p1, page, PROT_READ | PROT_WRITE | PROT_EXEC);
  snprintf(buf, sizeof buf, "plain_then_mprotect_rwx: mmap=%s mprotect=%d errno=%d\n",
           p1 == MAP_FAILED ? "FAIL" : "ok", rc1, rc1 == 0 ? 0 : errno);
  append(buf);

  // 2. MAP_JIT mmap RWX directly
  void *p2 = mmap(NULL, page, PROT_READ | PROT_WRITE | PROT_EXEC,
                  MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0);
  snprintf(buf, sizeof buf, "mmap_jit_rwx: %s errno=%d\n", p2 == MAP_FAILED ? "FAIL" : "ok",
           p2 == MAP_FAILED ? errno : 0);
  append(buf);

  // 3. W^X toggle on plain mapping: write, mprotect RX, execute a ret stub
  void *p3 = mmap(NULL, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int rc3 = -1, rc3b = -1, exec_ok = -1;
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
  snprintf(buf, sizeof buf, "plain_write_rx_exec: mprotect_rx=%d exec=%d errno=%d\n", rc3, exec_ok,
           rc3 == 0 ? 0 : errno);
  append(buf);

  // 4. pthread_jit_write_protect_np availability
  void *sym = dlsym(RTLD_DEFAULT, "pthread_jit_write_protect_np");
  snprintf(buf, sizeof buf, "pthread_jit_write_protect_np: %s\n", sym ? "present" : "absent");
  append(buf);
  (void)rc3b;
}
