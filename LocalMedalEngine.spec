# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[('ffmpeg/ffmpeg.exe', 'ffmpeg'), ('ffmpeg/ffprobe.exe', 'ffmpeg')],
    datas=[('core.py', '.')],
    hiddenimports=['engineio.async_drivers.threading', 'googleapiclient.discovery', 'google_auth_oauthlib.flow', 'google.auth.transport.requests', 'pkg_resources.py2_warn'],
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
    a.binaries,
    a.datas,
    [],
    name='LocalMedalEngine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
