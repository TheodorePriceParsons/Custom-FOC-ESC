"""Simulated ESC that speaks the bench protocol, for developing and checking the host suite
without hardware. It mirrors foc.c / bench.c: same modes, PI loops, anti-windup, deadband,
watchdog, capture kinds and limits. The motor parameters are plausible GM4108H-ish guesses,
not measurements.
"""
from __future__ import annotations

import io
import math
import struct

import numpy as np

F_LOOP = 10377.0
DT = 1.0 / F_LOOP
CAP_N, CAP_CH, CAP_PRE = 2048, 4, 200
POLE_PAIRS = 11
ENC_CPR = 16384
AMPS_PER_COUNT = 3.3 / (4096 * 40 * 0.005)
IDLE, CALIB, TEST_PWM, OPENLOOP, ALIGN, VOLTAGE, CURRENT, SPEED, FAULT = range(9)
RUN_MODES = {OPENLOOP, ALIGN, VOLTAGE, CURRENT, SPEED}
MODE_NAMES = {"IDLE": IDLE, "CALIB": CALIB, "OPENLOOP": OPENLOOP, "ALIGN": ALIGN,
              "VOLTAGE": VOLTAGE, "CURRENT": CURRENT, "SPEED": SPEED}
LIM_V, LIM_I, LIM_W = 3.0, 1.0, 30.0


class Plant:
    def __init__(self, rng):
        self.R, self.L, self.lam = 5.0, 2.0e-3, 0.0125      # ohm, H, V.s (per phase, peak)
        self.J, self.B, self.Tc = 6.0e-5, 2.0e-4, 0.005      # kg m^2, N m s, N m
        self.ecc = math.radians(0.6)                          # magnet eccentricity error, mech
        self.rng = rng
        self.id = self.iq = self.w = 0.0
        self.th = 0.0

    @property
    def kt(self):
        return 1.5 * POLE_PAIRS * self.lam

    def step(self, vd, vq, dt):
        sub = 4
        h = dt / sub
        for _ in range(sub):
            we = POLE_PAIRS * self.w
            did = (vd - self.R * self.id + we * self.L * self.iq) / self.L
            diq = (vq - self.R * self.iq - we * self.L * self.id - we * self.lam) / self.L
            self.id += did * h
            self.iq += diq * h
            te = self.kt * self.iq
            if abs(self.w) < 1e-3 and abs(te) <= self.Tc:
                self.w = 0.0                                  # stiction
            else:
                tf = self.Tc * math.copysign(1.0, self.w if self.w else te) + self.B * self.w
                self.w += (te - tf) / self.J * h
            self.th += self.w * h

    def enc_raw(self):
        th_meas = self.th + self.ecc * math.sin(self.th + 0.7)
        return int(round(th_meas / (2 * math.pi) * ENC_CPR)) % ENC_CPR

    def meas(self, x):
        n = x + self.rng.normal(0, 0.003)
        return round(n / AMPS_PER_COUNT) * AMPS_PER_COUNT


class SimEsc:
    def __init__(self, seed=1):
        self.p = Plant(np.random.default_rng(seed))
        self.mode = IDLE
        self.fault = 0
        self.aligned = True
        self.vd_cmd = self.vq_cmd = self.id_cmd = self.iq_cmd = self.w_cmd = 0.0
        self.ol_v, self.ol_speed = 1.0, 6.28
        self.kp_i, self.ki_i = 1.0, 500.0
        self.kp_w, self.ki_w = 0.02, 0.31
        self.int_d = self.int_q = self.int_w = 0.0
        self.w_ref = 0.0
        self.spd_div = 0
        self.vel = 0.0
        self.enc_prev = self.p.enc_raw()
        self.vd_out = self.vq_out = 0.0
        self.v_pending = (0.0, 0.0)
        self.id = self.iq = 0.0
        self.isr_count = 0
        self.isr_max = 6200
        self.wd_last, self.wd_timeout = 0, 0
        self.cap = np.zeros((CAP_N, CAP_CH), dtype="<f4")
        self.cap_state, self.cap_n, self.cap_decim, self.cap_div = 0, 0, 1, 0
        self.cap_src, self.step_dst, self.step_val, self.step_en = None, None, 0.0, False
        self.prev_mode = IDLE

    # ---------------- ISR ----------------
    def _trip(self, f):
        self.fault, self.mode = f, FAULT

    def _on_enter(self, m):
        if m == SPEED:
            self.int_w, self.w_ref, self.spd_div, self.id_cmd = 0.0, self.vel, 0, 0.0
        if m in (VOLTAGE, CURRENT, SPEED) and not self.aligned:
            self._trip(4)
            return
        if m in (CURRENT, SPEED):
            self.int_d = self.int_q = 0.0
        if m == IDLE:
            self.fault = 0
        if m == ALIGN:
            self.aligned = True

    def _limit(self, vd, vq):
        vmax = (2 * 0.95 - 1) * 12.0 / math.sqrt(3)
        sd = sq = False
        if abs(vd) > vmax:
            vd, sd = math.copysign(vmax, vd), True
        vqm = math.sqrt(max(vmax ** 2 - vd ** 2, 0.0))
        if abs(vq) > vqm:
            vq, sq = math.copysign(vqm, vq), True
        return vd, vq, sd, sq

    def tick(self):
        p = self.p
        self.isr_count += 1
        vd_apply, vq_apply = self.v_pending if self.mode in RUN_MODES else (0.0, 0.0)
        if self.mode not in RUN_MODES:
            # IDLE/FAULT: low sides on -> phases shorted (brake): v = 0
            pass
        p.step(vd_apply, vq_apply, DT)
        raw = p.enc_raw()
        d = (raw - self.enc_prev + ENC_CPR // 2) % ENC_CPR - ENC_CPR // 2
        self.enc_prev = raw
        self.vel += 0.02 * (d * 2 * math.pi / ENC_CPR / DT - self.vel)
        self.id, self.iq = p.meas(p.id), p.meas(p.iq)
        if max(abs(p.id), abs(p.iq)) > 4.0:
            self._trip(1)
        if (self.wd_timeout and self.mode in RUN_MODES
                and self.isr_count - self.wd_last > self.wd_timeout):
            self._trip(7)
        if self.mode != self.prev_mode:
            self.prev_mode = self.mode
            self._on_enter(self.mode)
            self.prev_mode = self.mode

        vd = vq = 0.0
        sd = sq = False
        if self.mode == VOLTAGE:
            vd, vq, sd, sq = self._limit(self.vd_cmd, self.vq_cmd)
        elif self.mode in (CURRENT, SPEED):
            if self.mode == SPEED:
                self.spd_div += 1
                if self.spd_div >= 10:
                    self.spd_div = 0
                    dts = 10 * DT
                    step = 50.0 * dts
                    dw = self.w_cmd - self.w_ref
                    self.w_ref += max(-step, min(step, dw))
                    if self.w_cmd == 0.0 and abs(self.w_ref) < 0.01 and abs(self.vel) < 1.0:
                        self.int_w, self.iq_cmd = 0.0, 0.0
                    else:
                        ew = self.w_ref - self.vel
                        u = self.kp_w * ew + self.int_w
                        us = max(-0.3, min(0.3, u))
                        sat = (u != us) or self.vq_sat
                        if not sat or ew * u < 0:
                            self.int_w += self.ki_w * ew * dts
                        self.iq_cmd = us
            ed, eq = self.id_cmd - self.id, self.iq_cmd - self.iq
            ud, uq = self.kp_i * ed + self.int_d, self.kp_i * eq + self.int_q
            vd, vq, sd, sq = self._limit(ud, uq)
            if not sd or ed * ud < 0:
                self.int_d += self.ki_i * ed * DT
            if not sq or eq * uq < 0:
                self.int_q += self.ki_i * eq * DT
        self.vd_out, self.vq_out, self.vq_sat = vd, vq, sq
        self.v_pending = (vd, vq)                    # PWM update lands next period

        if self.cap_state == 1:
            self.cap_div += 1
            if self.cap_div >= self.cap_decim:
                self.cap_div = 0
                if self.cap_n == CAP_PRE and self.step_en:
                    for name in self.step_dst:
                        setattr(self, name, self.step_val)
                self.cap[self.cap_n] = [getattr(self, s) if s != "theta" else
                                        (p.th % (2 * math.pi)) for s in self.cap_src]
                self.cap_n += 1
                if self.cap_n >= CAP_N:
                    self.cap_state = 2

    vq_sat = False

    # ---------------- protocol ----------------
    KINDS = {
        "VD": (VOLTAGE, LIM_V, ["vd_cmd", "id", "iq", "vel"], ["vd_cmd"]),
        "ID": (CURRENT, LIM_I, ["id_cmd", "id", "iq", "vd_out"], ["id_cmd"]),
        "IQ": (CURRENT, LIM_I, ["iq_cmd", "iq", "id", "vq_out"], ["iq_cmd"]),
        "W": (SPEED, LIM_W, ["w_ref", "vel", "iq_cmd", "iq"], ["w_cmd", "w_ref"]),
        "NONE": (None, 0.0, ["w_ref", "vel", "iq", "theta"], []),
    }
    VARS = {"vd": ("vd_cmd", LIM_V), "vq": ("vq_cmd", LIM_V), "id": ("id_cmd", LIM_I),
            "iq": ("iq_cmd", LIM_I), "w": ("w_cmd", LIM_W), "ol_v": ("ol_v", LIM_V),
            "ol_speed": ("ol_speed", 200.0)}

    def handle(self, line: str) -> bytes:
        a = line.split()
        if not a:
            return b""
        self.wd_last = self.isr_count
        c = a[0]
        try:
            if c == "PING":
                return b"OK\n"
            if c == "INFO":
                return (f"OK proto=1 f_loop={int(F_LOOP)} cap_n={CAP_N} cap_ch={CAP_CH} "
                        f"cap_pre={CAP_PRE} pole_pairs={POLE_PAIRS} build=SIM\n").encode()
            if c == "WD":
                ms = float(a[1])
                self.wd_timeout = int(ms * F_LOOP / 1000)
                return b"OK\n"
            if c == "MODE":
                if a[1] not in MODE_NAMES:
                    return b"ERR ARG\n"
                m = MODE_NAMES[a[1]]
                if self.mode == FAULT and m != IDLE:
                    return b"ERR FAULT\n"
                self.mode = m
                return b"OK\n"
            if c == "SET":
                v = float(a[2])
                if a[1] in self.VARS:
                    attr, lim = self.VARS[a[1]]
                    if abs(v) > lim:
                        return b"ERR RANGE\n"
                    setattr(self, attr, v)
                    return b"OK\n"
                if v < 0:
                    return b"ERR RANGE\n"
                if a[1] in ("kp_i", "ki_i", "kp_w", "ki_w"):
                    setattr(self, a[1], v)
                    return b"OK\n"
                return b"ERR ARG\n"
            if c == "GET":
                return (f"OK mode={self.mode} fault={self.fault} aligned={int(self.aligned)} "
                        f"vel={self.vel:.6f} w_ref={self.w_ref:.6f} iq={self.iq:.6f} id={self.id:.6f} "
                        f"vd={self.vd_out:.6f} vq={self.vq_out:.6f} vbus=12.000000 isr_max={self.isr_max} "
                        f"kp_i={self.kp_i:.6f} ki_i={self.ki_i:.6f} kp_w={self.kp_w:.6f} "
                        f"ki_w={self.ki_w:.6f}\n").encode()
            if c == "CLRMAX":
                return b"OK\n"
            if c == "CAP":
                if self.cap_state == 1:
                    return b"ERR BUSY\n"
                mode, lim, src, dst = self.KINDS[a[1]]
                d = float(a[2])
                if not 1 <= d <= 64:
                    return b"ERR ARG\n"
                step = len(a) >= 4
                sv = float(a[3]) if step else 0.0
                if step and (not dst or abs(sv) > lim):
                    return b"ERR RANGE\n"
                if mode is not None and self.mode != mode:
                    return b"ERR MODE\n"
                self.cap_src, self.step_dst, self.step_val, self.step_en = src, dst, sv, step
                self.cap_decim, self.cap_div, self.cap_n, self.cap_state = int(d), 0, 0, 1
                return b"OK\n"
            if c == "STAT":
                return f"OK state={self.cap_state} n={self.cap_n}\n".encode()
            if c == "DUMP":
                if self.cap_state != 2:
                    return b"ERR NODATA\n"
                return (f"OK n={CAP_N} ch={CAP_CH}\n".encode()
                        + self.cap.astype("<f4").tobytes() + b"END\n")
            if c == "ABORT":
                self.cap_state = 0
                return b"OK\n"
        except (IndexError, ValueError, KeyError):
            return b"ERR ARG\n"
        return b"ERR CMD\n"


class SimTransport:
    """Byte-level stand-in for the serial port. Time only advances in sleep()."""

    def __init__(self, seed=1):
        self.esc = SimEsc(seed)
        self.out = io.BytesIO()
        self.pos = 0
        self._line = b""
        self.esc.out_banner = True
        self._push(b"# bench ready\n")

    def _push(self, b):
        self.out.seek(0, 2)
        self.out.write(b)

    def write(self, data: bytes):
        for ch in data:
            if ch == 10:
                self._push(self.esc.handle(self._line.decode()))
                self._line = b""
            elif ch != 13:
                self._line += bytes([ch])

    def readline(self) -> bytes:
        self.out.seek(self.pos)
        line = self.out.readline()
        self.pos += len(line)
        return line

    def read(self, n: int) -> bytes:
        self.out.seek(self.pos)
        b = self.out.read(n)
        self.pos += len(b)
        return b

    def sleep(self, s: float):
        for _ in range(int(round(s * F_LOOP))):
            self.esc.tick()

    def close(self):
        pass


if __name__ == "__main__":
    # quick smoke test
    t = SimTransport()
    for cmd in ("PING", "INFO", "SET w 10", "MODE SPEED"):
        t.write((cmd + "\n").encode())
    t.sleep(2.0)
    t.write(b"GET\n")
    while (line := t.readline()):
        print(line.decode().strip())
    print(struct.calcsize("<f"))
