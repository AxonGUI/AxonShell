# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/workspace/AxonShell/examples/files/main.py'],
    pathex=['/workspace/AxonShell/src'],
    binaries=[],
    datas=[('/workspace/AxonShell/examples/files/web', 'web'), ('/workspace/AxonShell/examples/files/workspace', 'workspace'), ('/workspace/AxonShell/examples/files/vendor/axon.umd.cjs', 'vendor'), ('/workspace/AxonShell/assets/axon-mark.svg', 'brand.svg'), ('/workspace/AxonShell/src/axon_shell/assets/shell.css', 'axon-shell'), ('/workspace/AxonShell/src/axon_shell/assets/shell.js', 'axon-shell')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AxonFiles',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/workspace/AxonShell/src/axon_shell/assets/icon-256.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AxonFiles',
)
