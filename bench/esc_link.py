"""Host side of the bench protocol (see PROTOCOL.md).

EscLink wraps a transport with write/readline/read/sleep. SerialTransport talks to the
real board; sim.SimTransport runs a plant model with the same protocol.
"""
from __future__ import annotations

import time

import numpy as np

MODES = {0: "IDLE", 1: "CALIB", 2: "TEST_PWM", 3: "OPENLOOP", 4: "ALIGN", 5: "VOLTAGE",
         6: "CURRENT", 7: "SPEED", 8: "FAULT"}
FAULTS = {0: "NONE", 1: "OVERCURRENT", 2: "DRV_NFAULT", 3: "NOT_CALIBRATED", 4: "NOT_ALIGNED",
          5: "VBUS_LOW", 6: "ALIGN_NO_MOTION", 7: "WATCHDOG", 8: "ESTOP"}


class EscError(RuntimeError):
    pass


class SerialTransport:
    def __init__(self, port: str, baud: int = 115200, timeout: float = 1.0):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def write(self, data: bytes) -> None:
        self.ser.write(data)

    def readline(self) -> bytes:
        return self.ser.readline()

    def read(self, n: int) -> bytes:
        return self.ser.read(n)

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def close(self) -> None:
        self.ser.close()


def _parse_kv(text: str) -> dict:
    out = {}
    for tok in text.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            try:
                out[k] = float(v) if any(c in v for c in ".en") else int(v)
            except ValueError:
                out[k] = v
    return out


class EscLink:
    HEARTBEAT_S = 0.1

    def __init__(self, transport, watchdog_ms: int = 300, log=None):
        self.t = transport
        self.log = log
        self.watchdog_ms = watchdog_ms
        self.info = {}

    # ---------- low level ----------
    def cmd(self, line: str) -> str:
        self.t.write((line + "\n").encode())
        for _ in range(20):
            raw = self.t.readline()
            if not raw:
                raise EscError(f"timeout waiting for reply to '{line}'")
            reply = raw.decode(errors="replace").strip()
            if not reply or reply.startswith("#"):
                continue                          # banner / comments
            if self.log:
                self.log(f"> {line}  < {reply}")
            if reply.startswith("ERR"):
                raise EscError(f"'{line}' -> {reply}")
            if reply.startswith("OK"):
                return reply[2:].strip()
        raise EscError(f"no OK/ERR reply to '{line}'")

    # ---------- session ----------
    def open(self) -> dict:
        self.cmd("PING")
        raw = self.cmd("INFO")
        build = raw.split("build=", 1)[1] if "build=" in raw else "?"
        self.info = _parse_kv(raw.split("build=")[0])
        self.info["build"] = build
        self.cmd("ABORT")
        self.cmd(f"WD {self.watchdog_ms}")
        return self.info

    def safe_stop(self) -> None:
        """Best effort: never raises. Ramp to zero, then idle, then disarm the watchdog."""
        for line in ("SET w 0", "SET iq 0", "SET id 0", "SET vd 0", "SET vq 0"):
            try:
                self.cmd(line)
            except Exception:
                pass
        try:
            self.cmd("MODE IDLE")
            self.cmd("WD 0")
        except Exception:
            pass

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.safe_stop()
        return False

    # ---------- helpers ----------
    def get(self) -> dict:
        return _parse_kv(self.cmd("GET"))

    def set(self, name: str, value: float) -> None:
        self.cmd(f"SET {name} {value:.6g}")

    def mode(self, name: str) -> None:
        self.cmd(f"MODE {name}")
        self.hold(0.02)                           # one ISR applies the mode change
        st = self.get()
        if MODES.get(st["mode"]) != name:
            raise EscError(f"MODE {name} rejected: now {MODES.get(st['mode'])}, "
                           f"fault {FAULTS.get(st['fault'], st['fault'])}")

    def hold(self, seconds: float) -> None:
        """Wait while kicking the watchdog."""
        end = seconds
        while end > 0:
            dt = min(self.HEARTBEAT_S, end)
            self.t.sleep(dt)
            end -= dt
            self.cmd("PING")

    def record(self, kind: str, decim: int, step: float | None = None, timeout: float = 10.0) -> None:
        """Arm a capture (optionally with a step at sample cap_pre) and wait until it is full.
        The drive keeps running afterwards; stop it before dump() so it doesn't sit loaded."""
        line = f"CAP {kind} {decim}" + (f" {step:.6g}" if step is not None else "")
        self.cmd(line)
        n = self.info.get("cap_n", 2048)
        f_loop = self.info.get("f_loop", 10377)
        self.hold(n * decim / f_loop)
        waited = 0.0
        while True:
            st = _parse_kv(self.cmd("STAT"))
            if st.get("state") == 2:
                break
            if waited > timeout:
                raise EscError("capture timeout")
            self.hold(0.05)
            waited += 0.05

    def dump(self) -> np.ndarray:
        self.t.write(b"DUMP\n")
        while True:
            raw = self.t.readline()
            if not raw:
                raise EscError("timeout waiting for DUMP header")
            line = raw.decode(errors="replace").strip()
            if line.startswith("ERR"):
                raise EscError(f"DUMP -> {line}")
            if line.startswith("OK"):
                break
        kv = _parse_kv(line)
        n, ch = int(kv["n"]), int(kv["ch"])
        nbytes = n * ch * 4
        buf = b""
        while len(buf) < nbytes:
            chunk = self.t.read(nbytes - len(buf))
            if not chunk:
                raise EscError(f"DUMP short read: {len(buf)}/{nbytes} bytes")
            buf += chunk
        end = self.t.readline().decode(errors="replace").strip()
        if end != "END":
            raise EscError(f"DUMP trailer missing (got '{end}')")
        return np.frombuffer(buf, dtype="<f4").reshape(n, ch).astype(float)

    def time_axis(self, decim: int) -> tuple[np.ndarray, float]:
        """Sample times and the step time for a capture with this decimation."""
        n = self.info.get("cap_n", 2048)
        dt = decim / self.info.get("f_loop", 10377)
        return np.arange(n) * dt, self.info.get("cap_pre", 200) * dt
