# PyInstaller spec for the saidso engine.
#
# Built as a one-folder bundle rather than one file: a single .exe unpacks
# hundreds of megabytes to a temp directory on every launch, which makes the
# desktop app slow to start and leaves debris if it is killed. A folder starts
# instantly and Electron ships it as an extraResource either way.
#
# Build from the repository root:
#     pyinstaller packaging/saidso-engine.spec --noconfirm \
#         --distpath dist/engine --workpath build/pyinstaller

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is injected by PyInstaller. Paths are resolved against it rather than
# the working directory so the build works from anywhere.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas, binaries, hiddenimports = [], [], []

# The model runtime and the media decoder both carry native libraries and data
# files that no static analysis will find: ctranslate2's DLLs, av's bundled
# ffmpeg, faster-whisper's Silero VAD weights.
for package in ("faster_whisper", "ctranslate2", "av", "tokenizers", "onnxruntime"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# Windows audio capture. Absent on other platforms, which is not an error.
try:
    audio_datas, audio_binaries, audio_hidden = collect_all("pyaudiowpatch")
    datas += audio_datas
    binaries += audio_binaries
    hiddenimports += audio_hidden
except Exception:
    pass

# saidso imports its own submodules lazily so an optional dependency can be
# missing without breaking startup — which also hides them from the analysis.
hiddenimports += collect_submodules("saidso")
hiddenimports += ["tomli_w"]

analysis = Analysis(
    [os.path.join(SPECPATH, "engine_entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Nothing here draws a window; the desktop shell is the UI. The rest are
    # transitive dependencies of the Hugging Face stack that no code path in
    # saidso reaches — pyarrow alone is ~50 MB of Arrow libraries pulled in for
    # a dataset loader that is never called. Excluding them is worth roughly a
    # quarter of the bundle. Anything removed here is verified by actually
    # transcribing with the frozen build, not by the build succeeding.
    excludes=[
        "tkinter", "matplotlib", "PyQt5", "PySide6", "IPython", "pytest",
        "pyarrow", "pandas", "datasets", "PIL", "scipy", "sympy",
        "transformers", "torch", "torchaudio", "torchvision",
        "notebook", "jupyter", "sqlalchemy",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="saidso-engine",
    debug=False,
    strip=False,
    upx=False,
    console=True,          # stdout carries the handshake line; stdin signals parent death
    disable_windowed_traceback=False,
)

collected = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="saidso-engine",
)
