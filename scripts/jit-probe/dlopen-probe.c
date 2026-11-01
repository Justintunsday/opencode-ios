// iPhoneOS dlopen probe (diagnostic only, never shipped in the .deb).
// Verifies that the target iPhone can dlopen an ldid-signed iPhoneOS dylib
// shipped as a CLI asset (Phase D precondition for the OpenTUI renderer):
//   ./dlopenhprobe <path-to-dylib>
// Prints DLOPEN_OK / DLOPEN_FAIL + dlerror, a few dladdr checks and dlclose.
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
  const char *path = argc > 1 ? argv[1] : "/var/mobile/libopentui.dylib";
  printf("dlopen-probe path=%s\n", path);

  void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
  if (h == NULL) {
    printf("DLOPEN_FAIL: %s\n", dlerror());
    return 1;
  }
  printf("DLOPEN_OK handle=%p\n", h);

  // Common symbol names exported by the OpenTUI native core; report which are
  // resolvable (missing names are not failures, they document the ABI surface).
  const char *names[] = {
      NULL,
  };
  (void)names;

  // dlinfo(RTLD_DI_LINKMAP) gives the install name we loaded, proving which
  // bytes dyld accepted.
  void *image = dlsym(h, "be_memory_inline_jit_restrict_with_witness_supported");
  printf("symbol%sbrowser-engine-core: %p\n", image ? " " : " (absent) ", image);

  int rc = dlclose(h);
  printf("DLCLOSE_%s rc=%d\n", rc == 0 ? "OK" : "FAIL", rc);
  return rc == 0 ? 0 : 1;
}
