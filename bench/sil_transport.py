"""Software-in-the-loop transport: the real firmware (foc.c, foc_math.c, bench.c) compiled for
the PC and closed around the plant model in sil/plant/. Same byte stream as the serial port,
so EscLink and the whole suite run unchanged.

    python run_bench.py --sil

The shared library is built on first use (and whenever a source is newer) with the gcc/g++
or clang/clang++ on PATH. On Windows use MinGW-w64 (MSYS2: pacman -S mingw-w64-ucrt-x86_64-gcc).
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SIL = os.path.join(HERE, "sil")
FW = os.path.normpath(os.path.join(HERE, "..", "firmware", "App"))
BUILD = os.path.join(SIL, "build")
F_LOOP = 10377.0

INCLUDES = [os.path.join(SIL, "stubs"),          # first: our main.h replaces Core/Inc/main.h
            os.path.join(SIL, "plant"),
            os.path.join(FW, "foc"), os.path.join(FW, "config"),
            os.path.join(FW, "drivers"), os.path.join(FW, "bench")]
C_SOURCES = [os.path.join(FW, "foc", "foc.c"),           # firmware, unmodified
             os.path.join(FW, "foc", "foc_math.c"),
             os.path.join(SIL, "stubs", "drivers_sil.c"), # PC drivers
             os.path.join(SIL, "plant", "plant.c"),
             os.path.join(SIL, "sil.c")]
CXX_SOURCES = [os.path.join(SIL, "bench_sil.cpp")]          # includes firmware bench.c
DEPS = C_SOURCES + CXX_SOURCES + [os.path.join(FW, "bench", "bench.c")] + [
    os.path.join(d, f) for d in INCLUDES for f in os.listdir(d) if f.endswith((".h", ".hpp"))]


def _libname() -> str:
    if sys.platform == "win32":
        return "escsil.dll"
    if sys.platform == "darwin":
        return "libescsil.dylib"
    return "libescsil.so"


def _tools() -> tuple[str, str]:
    for cc, cxx in (("gcc", "g++"), ("clang", "clang++"), ("cc", "c++")):
        if shutil.which(cc) and shutil.which(cxx):
            return cc, cxx
    raise RuntimeError("SIL needs a host C/C++ compiler (gcc/g++ or clang/clang++) on PATH. "
                       "Windows: MSYS2 MinGW-w64 gcc, or run from WSL.")


def build(force: bool = False, verbose: bool = False) -> str:
    """Compile the firmware + plant into a shared library. Returns its path."""
    os.makedirs(BUILD, exist_ok=True)
    lib = os.path.join(BUILD, _libname())
    if (not force and os.path.exists(lib)
            and os.path.getmtime(lib) >= max(os.path.getmtime(p) for p in DEPS)):
        return lib
    cc, cxx = _tools()
    inc = [f"-I{d}" for d in INCLUDES]
    common = ["-O2", "-g", "-DSIL=1", "-Wall", "-Wno-unused-function"]
    if sys.platform != "win32":
        common.append("-fPIC")
    objs = []
    for src in C_SOURCES:
        obj = os.path.join(BUILD, os.path.splitext(os.path.basename(src))[0] + ".o")
        _run([cc, "-std=c11", *common, *inc, "-c", src, "-o", obj], verbose)
        objs.append(obj)
    for src in CXX_SOURCES:
        obj = os.path.join(BUILD, os.path.splitext(os.path.basename(src))[0] + ".o")
        _run([cxx, "-std=c++17", *common, *inc, "-c", src, "-o", obj], verbose)
        objs.append(obj)
    link = [cxx, "-shared", *objs, "-o", lib]
    if sys.platform == "win32":
        link += ["-static-libgcc", "-static-libstdc++"]
    else:
        link.append("-lm")
    _run(link, verbose)
    return lib


def _run(cmd, verbose):
    if verbose:
        print(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"SIL build failed:\n{' '.join(cmd)}\n{r.stdout}{r.stderr}")


def _load(path: str) -> ctypes.CDLL:
    """Load a private copy: the firmware keeps its state in globals, so each SilTransport
    needs its own instance of the library to start from reset."""
    fd, copy = tempfile.mkstemp(suffix=os.path.splitext(path)[1], prefix="escsil_")
    os.close(fd)
    shutil.copyfile(path, copy)
    lib = ctypes.CDLL(copy)
    lib.sil_init.argtypes = [ctypes.c_uint64]
    lib.sil_init.restype = ctypes.c_int
    lib.sil_param.argtypes = [ctypes.c_char_p, ctypes.c_double]
    lib.sil_param.restype = ctypes.c_int
    lib.sil_truth.argtypes = [ctypes.c_char_p]
    lib.sil_truth.restype = ctypes.c_double
    lib.sil_run.argtypes = [ctypes.c_uint32]
    lib.sil_write.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
    lib.sil_read.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
    lib.sil_read.restype = ctypes.c_uint32
    lib.sil_press_estop.argtypes = []
    lib._copy_path = copy
    return lib


class SilTransport:
    """Byte-level stand-in for the serial port, backed by the compiled firmware.
    Time only advances in sleep(); commands are handled between control periods."""

    is_sil = True

    def __init__(self, seed: int = 1, params: dict | None = None, verbose_build: bool = False):
        self.lib = _load(build(verbose=verbose_build))
        for k, v in (params or {}).items():
            self.param(k, v)
        rc = self.lib.sil_init(seed)
        if rc != 0:
            raise RuntimeError(f"sil_init failed ({rc})")
        self._buf = b""
        self._frac = 0.0
        self.sleep(0.25)          # boot: CALIB averages 2048 samples (~0.2 s)

    # ---- plant / test hooks ----
    def param(self, name: str, value: float) -> None:
        if not self.lib.sil_param(name.encode(), float(value)):
            raise KeyError(f"unknown plant parameter '{name}'")

    def truth(self, name: str) -> float:
        return self.lib.sil_truth(name.encode())

    def press_estop(self) -> None:
        self.lib.sil_press_estop()

    # ---- transport API (same as SerialTransport) ----
    def write(self, data: bytes) -> None:
        self.lib.sil_write(data, len(data))

    def _pull(self):
        out = ctypes.create_string_buffer(65536)
        while True:
            n = self.lib.sil_read(out, len(out))
            if n == 0:
                break
            self._buf += out.raw[:n]

    def readline(self) -> bytes:
        self._pull()
        i = self._buf.find(b"\n")
        if i < 0:
            line, self._buf = self._buf, b""
        else:
            line, self._buf = self._buf[:i + 1], self._buf[i + 1:]
        return line

    def read(self, n: int) -> bytes:
        self._pull()
        b, self._buf = self._buf[:n], self._buf[n:]
        return b

    def sleep(self, s: float) -> None:
        x = s * F_LOOP + self._frac
        n = int(x)
        self._frac = x - n
        if n > 0:
            self.lib.sil_run(n)

    def close(self) -> None:
        pass


if __name__ == "__main__":
    t = SilTransport()
    for cmd in ("PING", "INFO", "GET"):
        t.write((cmd + "\n").encode())
    while (line := t.readline()):
        print(line.decode().rstrip())
