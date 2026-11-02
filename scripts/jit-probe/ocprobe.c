// Minimal iPhoneOS dylib for device diagnostics: can the jailbroken iPhone
// execute code from a dynamically loaded third-party dylib at all?
// Used by .github/workflows/jit-probe.yml (diagnostic only, never shipped).
int ocprobe_add(int a, int b) { return a + b; }

int ocprobe_version(void) { return 1; }
