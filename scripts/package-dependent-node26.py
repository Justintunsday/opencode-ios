#!/usr/bin/env python3
"""Assemble OpenCode with a strict dependency on the standalone node26 deb."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'packaging/verify'))
from deb_archive import build_deb, read_deb, sha256, safe_name
from check_macho import audit, MH_DYLIB

APP = 'var/jb/usr/lib/opencode'
RUNTIME = 'var/jb/usr/lib/node26'
DOC = 'var/jb/usr/share/doc/opencode'
RENDERER = 'assets/@opentui/core-ios-arm64/libopentui.dylib'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node-package', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--pin', type=Path, default=ROOT/'packaging/node26-dependent/pins.json')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/opencode-node26-dependent')
    args = parser.parse_args()
    pin = json.loads(args.pin.read_text(encoding='utf-8'))
    checks = []

    def require(condition, label):
        if not condition:
            raise ValueError(label)
        checks.append({'name':label,'status':'PASS'})

    require(sha256(args.node_package.read_bytes()) == pin['node_package_sha256'], 'Pinned runtime deb SHA')
    node_control, node_files, node_links = read_deb(args.node_package)
    require(node_control['Package'] == 'node26', 'Independent runtime package name')
    require(node_control['Version'] == pin['node_package_version'], 'Exact runtime package version')
    require(node_control['Architecture'] == 'iphoneos-arm64', 'Runtime architecture')
    require(node_control['Author'] == 'nodejs' and node_control['Maintainer'].startswith('nodejs <'), 'Runtime author nodejs')
    require(sha256(node_files[RUNTIME+'/node'][0]) == pin['node_sha256'], 'External runtime executable SHA')
    manifest = json.loads(node_files[RUNTIME+'/runtime-manifest.json'][0])
    require(manifest['node_version'] == '26.13.0' and manifest['build']['ffi_support'].startswith('enabled'), 'Node 26.13.0 and FFI enabled')
    require(any(row['file'].endswith('0016-ios-v8-jobs-join-only.patch') for row in manifest['source']['patches']), 'Foreground V8 JobHandles fix')
    require('var/jb/usr/bin/node' in node_files and 'var/jb/usr/bin/node26' not in node_files, 'Default command node')

    cli_manifest = json.loads((args.cli/'bundle-manifest.json').read_text(encoding='utf-8'))
    mjs = (args.cli/'opencode.mjs').read_bytes()
    require(sha256(mjs) == pin['cli_sha256'], 'Pinned CLI SHA')
    require(cli_manifest['variant'] == 'node26', 'CLI variant')
    require(cli_manifest['bundle']['opencode_mjs']['sha256'] == pin['cli_sha256'], 'CLI manifest identity')
    require(b'Tree-sitter workers are disabled on iPhoneOS' in mjs, 'iOS worker-isolate guard')
    for line in (args.cli/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = line.split(None,1)
        name = safe_name(name.lstrip('*'))
        file = args.cli/name
        require(not file.is_symlink() and sha256(file.read_bytes()) == digest, 'CLI artifact checksum '+name)
    files = {
        APP+'/cli/opencode.mjs':(mjs,0o644),
        APP+'/cli/bundle-manifest.json':((args.cli/'bundle-manifest.json').read_bytes(),0o644),
    }
    expected_assets = set()
    for item in cli_manifest['bundle']['assets']['files']:
        name = 'assets/'+safe_name(item['path'])
        path = args.cli/name
        payload = path.read_bytes()
        require(not path.is_symlink() and len(payload) == item['bytes'] and sha256(payload) == item['sha256'], 'Asset identity '+name)
        files[APP+'/cli/'+name] = (payload,0o755 if name == RENDERER else 0o644)
        expected_assets.add(name)
    actual_assets = {p.relative_to(args.cli).as_posix() for p in (args.cli/'assets').rglob('*') if p.is_file()}
    require(actual_assets == expected_assets, 'Exact asset inventory')
    require(sha256((args.cli/RENDERER).read_bytes()) == pin['renderer_sha256'], 'Pinned renderer SHA')
    audit(args.cli/RENDERER, filetypes=(MH_DYLIB,))
    require(True, 'Renderer iPhoneOS ARM64 dylib')
    launcher = (ROOT/'packaging/node26-dependent/opencode').read_bytes()
    require(b'$PREFIX/usr/lib/node26/node' in launcher and b'--single-threaded --no-warnings' in launcher, 'External runtime launcher and required flags')
    require(b'OTUI_ASSET_ROOT' in launcher and b'OPENCODE_IOS_RUNTIME_ASSETS' in launcher, 'Rootless renderer asset contract')
    files['var/jb/usr/bin/opencode'] = (launcher,0o755)
    files[APP+'/runtime/dependency.json'] = ((json.dumps(pin,indent=2)+'\n').encode(),0o644)
    for name in ('INSTALL.md','VERIFICATION.md','KNOWN_LIMITATIONS.md','OPENTUI_IOS.md','OPENCODE_BUILD.md','NODE26_EXTERNAL_RUNTIME.md','NODE26_EXTERNAL_DEVICE_RESULTS.md'):
        files[DOC+'/'+name] = ((ROOT/'docs'/name).read_bytes(),0o644)
    for name in ('LICENSE','NOTICE'):
        files[DOC+'/'+name] = ((ROOT/name).read_bytes(),0o644)
    files[DOC+'/device-smoke.sh'] = ((ROOT/'packaging/rootless/usr/share/doc/opencode/device-smoke.sh').read_bytes(),0o755)
    links = {
        APP+'/runtime/node':'../../node26/node',
        APP+'/runtime/runtime-manifest.json':'../../node26/runtime-manifest.json',
        APP+'/runtime/entitlements.xml':'../../node26/entitlements.xml',
    }
    require(APP+'/runtime/node' not in files, 'No embedded runtime executable')
    require(all(target.startswith('../../node26/') for target in links.values()), 'Legacy paths point to dependency')
    installed_kib = (sum(len(data) for data,_ in files.values())+1023)//1024
    dependency = f"node26 (= {pin['node_package_version']})"
    control = f'''Package: opencode
Version: {pin['opencode_version']}
Architecture: iphoneos-arm64
Maintainer: OpenCode iOS port maintainers <opencode-ios-port@users.noreply.github.com>
Installed-Size: {installed_kib}
Section: Development
Priority: optional
Depends: firmware (>= 15.0), {dependency}
Recommends: git
Homepage: https://github.com/Justintunsday/opencode-ios
Description: OpenCode v2 native TUI using the standalone Node.js 26 runtime
 Experimental {pin['experimental_label']} rootless iPhoneOS ARM64 package.
 Uses node26 package version {pin['node_package_version']}; no embedded Node binary.
 CLI and renderer assets remain under /var/jb/usr/lib/opencode/cli.
 The stable v2.2.5-ios.5 release is unchanged.
'''.encode()
    deb = build_deb(control,files,links,int(pin['source_date_epoch']))
    args.output.mkdir(parents=True,exist_ok=True)
    filename = 'OpenCode-iOS-rootless-node26.deb'
    (args.output/filename).write_bytes(deb)
    node_filename = args.node_package.name
    (args.output/node_filename).write_bytes(args.node_package.read_bytes())
    report = dict(package='opencode',version=pin['opencode_version'],variant='node26-external',experimental_label=pin['experimental_label'],
                  depends=dependency,runtime_embedded=False,source_pins=pin,file=filename,bytes=len(deb),sha256=sha256(deb),
                  device_status='UNVERIFIED ON DEVICE (CI assembly only)',static_checks=checks,symlinks=links,
                  files=[dict(path=name,bytes=len(data),mode=oct(mode),sha256=sha256(data)) for name,(data,mode) in sorted(files.items())])
    encoded = (json.dumps(report,indent=2)+'\n').encode()
    (args.output/'package-report.json').write_bytes(encoded)
    (args.output/'SHA256SUMS').write_text(f'{sha256(deb)}  {filename}\n{pin["node_package_sha256"]}  {node_filename}\n{sha256(encoded)}  package-report.json\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:report[k] for k in ('file','version','bytes','sha256','depends','runtime_embedded')},indent=2))
    print('STATIC_CHECKS_PASS',len(checks))


if __name__ == '__main__':
    main()
