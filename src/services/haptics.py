"""Mouse haptics: a "tic" on a haptic mouse when the clock snaps to a border, over raw HID."""

from __future__ import annotations

import struct
import winreg

try:
    import hid
except Exception:  # pragma: no cover - module/DLL absent
    hid = None

_HAPTICS_USAGE_PAGE = 0x0E
_SIMPLE_HAPTIC_CONTROLLER = 0x01

WAVEFORM_ALIGN = 0x1013  # the snap-to-alignment-guide pulse

# Windows' own "Haptic signals" mouse setting, which we have to honor ourselves.
_MOUSE_FEEDBACK_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Windows\EnhancedPenSupport"


def _mouse_feedback() -> tuple[bool, float]:
    """(enabled, strength 0..1). Missing means this Windows lacks the setting (full strength);
    present but unreadable means off."""
    enabled, strength = True, 1.0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MOUSE_FEEDBACK_KEY) as k:
            try:
                value = winreg.QueryValueEx(k, "MouseFeedbackEnabled")[0]
            except OSError:
                pass
            else:
                enabled = isinstance(value, int) and bool(value)
            try:
                raw = winreg.QueryValueEx(k, "MouseFeedbackIntensity")[0]  # REG_QWORD = double bits
            except OSError:
                pass
            else:
                try:
                    frac = struct.unpack("<d", struct.pack("<Q", raw))[0]  # 0.25 / 0.5 / 0.75 / 1.0
                    strength = max(0.0, min(1.0, frac))
                except (TypeError, ValueError, OverflowError, struct.error):
                    enabled = False
    except OSError:
        pass
    return enabled, strength


def _parse_descriptor(desc: bytes) -> dict | None:
    """The report ids and bit positions needed to fire a waveform, or None if the device
    doesn't have them."""
    usage_page = logical_min = logical_max = report_size = report_count = report_id = 0
    usages: list[tuple[int, int]] = []
    coll_stack: list[tuple[int, int]] = []
    out_bits: dict[int, int] = {}
    lay = {
        "trigger_report_id": None, "trigger_bit": None, "trigger_size": None,
        "intensity_bit": None, "intensity_size": None, "intensity_max": 0,
        "cutoff_bit": None, "cutoff_size": None, "cutoff_min": 0,
        "output_bits": 0, "waveform_report_id": None,
    }
    _SZ = {0: 0, 1: 1, 2: 2, 3: 4}
    i, n = 0, len(desc)
    while i < n:
        prefix = desc[i]; i += 1
        if prefix == 0xFE:  # long item — skip
            i += 1 + (desc[i] if i < n else 0) + 1
            continue
        size = _SZ[prefix & 0x03]
        base = prefix & 0xFC
        data = 0
        for b in range(size):
            data |= desc[i + b] << (8 * b)
        i += size

        if base == 0x04:      # Usage Page (global)
            usage_page = data
        elif base == 0x14:    # Logical Minimum (global)
            logical_min = data
        elif base == 0x24:    # Logical Maximum (global)
            logical_max = data
        elif base == 0x74:    # Report Size (global)
            report_size = data
        elif base == 0x94:    # Report Count (global)
            report_count = data
        elif base == 0x84:    # Report ID (global)
            report_id = data
            out_bits.setdefault(report_id, 0)
        elif base == 0x08:    # Usage (local)
            usages.append((usage_page, data))
        elif base == 0xA0:    # Collection
            coll_stack.append(usages[-1] if usages else (usage_page, 0))
            usages = []
        elif base == 0xC0:    # End Collection
            if coll_stack:
                coll_stack.pop()
        elif base == 0x90:    # Output (main)
            off = out_bits.get(report_id, 0)
            for idx, (up, u) in enumerate(usages):
                fbit = off + idx * report_size
                if up == _HAPTICS_USAGE_PAGE and u == 0x21:      # Manual Trigger
                    lay["trigger_report_id"] = report_id
                    lay["trigger_bit"], lay["trigger_size"] = fbit, report_size
                elif up == _HAPTICS_USAGE_PAGE and u == 0x23:    # Intensity
                    lay["intensity_bit"], lay["intensity_size"] = fbit, report_size
                    lay["intensity_max"] = logical_max
                elif up == _HAPTICS_USAGE_PAGE and u == 0x28:    # Waveform Cutoff Time
                    lay["cutoff_bit"], lay["cutoff_size"] = fbit, report_size
                    lay["cutoff_min"] = logical_min
            out_bits[report_id] = off + report_size * report_count
            usages = []
        elif base == 0xB0:    # Feature (main)
            if (_HAPTICS_USAGE_PAGE, 0x10) in coll_stack:        # inside Waveform List
                lay["waveform_report_id"] = report_id
            usages = []
        elif base == 0x80:    # Input (main)
            usages = []

    if lay["trigger_report_id"] is None or lay["waveform_report_id"] is None:
        return None
    lay["output_bits"] = out_bits.get(lay["trigger_report_id"], 0)
    return lay


def _close(dev) -> None:
    if dev is not None:
        try:
            dev.close()
        except Exception:
            pass


class _Haptics:
    """Lazily opens the first HID haptics collection and fires waveforms on it."""

    def __init__(self) -> None:
        self._tried = False
        self._dev = None
        self._lay: dict | None = None
        self._ordinals: dict[int, int] = {}

    def _ensure(self) -> None:
        if self._tried:
            return
        self._tried = True
        if hid is None:
            return
        dev = None
        try:
            path = next(
                (d["path"] for d in hid.enumerate()
                 if d.get("usage_page") == _HAPTICS_USAGE_PAGE
                 and d.get("usage") == _SIMPLE_HAPTIC_CONTROLLER),
                None)
            if path is None:
                return
            dev = hid.device()
            dev.open_path(path)
            desc = bytes(dev.get_report_descriptor())
            lay = _parse_descriptor(desc)
            if lay is None:
                dev.close(); return
            raw = bytes(dev.get_feature_report(lay["waveform_report_id"], 64))
            ordinals, ordinal = {}, 3  # the listed waveforms are numbered from 3
            body = raw[1:]
            for j in range(0, len(body) - 1, 2):
                w = body[j] | (body[j + 1] << 8)
                if 0x1003 <= w <= 0x2FFF:   # a real (non None/Stop) waveform usage id
                    ordinals[w] = ordinal
                    ordinal += 1
            if not ordinals:
                dev.close(); return
            self._dev, self._lay, self._ordinals = dev, lay, ordinals
        except Exception:
            _close(dev)

    def _forget_device(self) -> None:
        """Drop a dead handle; the next fire looks it up again."""
        _close(self._dev)
        self._dev, self._tried = None, False

    def fire(self, waveform_id: int, strength: float = 1.0, retry: bool = True) -> None:
        """*strength* 0..1, scaled to the device's own intensity range."""
        self._ensure()
        dev, lay, ordinal = self._dev, self._lay, self._ordinals.get(waveform_id)
        if dev is None or lay is None or ordinal is None:
            return
        try:
            intensity = max(1, round(strength * lay["intensity_max"]))
            val = (ordinal << lay["trigger_bit"]) | (intensity << lay["intensity_bit"])
            if lay["cutoff_bit"] is not None:  # the device wants a cutoff; its minimum will do
                val |= lay["cutoff_min"] << lay["cutoff_bit"]
            nbytes = (lay["output_bits"] + 7) // 8
            report = [lay["trigger_report_id"]] + list(val.to_bytes(nbytes, "little"))
        except Exception:
            return
        try:
            written = dev.write(report)  # -1, not an exception, on a dead handle
        except Exception:
            written = -1
        if written < 0:
            self._forget_device()
            if retry:
                self.fire(waveform_id, strength, retry=False)


_singleton = _Haptics()


def prewarm() -> None:
    """Look up the haptic device now instead of at the first snap."""
    if _mouse_feedback()[0]:
        _singleton._ensure()


def snap_pulse() -> None:
    """The snap tic, at Windows' haptic-signals intensity. Silent when that setting is off,
    without a haptic device, or on any error."""
    enabled, strength = _mouse_feedback()
    if not enabled:
        return
    _singleton.fire(WAVEFORM_ALIGN, strength)
