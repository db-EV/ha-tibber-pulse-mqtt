from __future__ import annotations

import math
from typing import Any, Dict, Optional

# Per-phase mapping: current register -> (import power +P, export power -P)
# DSMR / Swedish HAN meters report phase currents (x1.7.0) as unsigned RMS
# magnitudes; the direction is only available via the separate directional
# active-power registers. This module derives a signed current from those.
_PHASE_MAP = {
    "1-0:31.7.0": ("1-0:21.7.0", "1-0:22.7.0"),  # L1
    "1-0:51.7.0": ("1-0:41.7.0", "1-0:42.7.0"),  # L2
    "1-0:71.7.0": ("1-0:61.7.0", "1-0:62.7.0"),  # L3
}

# Fallback if per-phase powers are absent: total import/export power
_TOTAL_IMPORT = "1-0:1.7.0"
_TOTAL_EXPORT = "1-0:2.7.0"


def _finite_num(value: Any) -> Optional[float]:
    """
    Return *value* as float if it is a real, finite number, else None.

    Explicitly rejects bool (a subclass of int) and non-finite floats
    (NaN/inf), which can slip through upstream parsers since payloads
    originate from untrusted MQTT input.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def apply_signed_current(obis: Dict[str, Any]) -> None:
    """
    Mutate *obis* in place: negate phase-current values while power flows
    towards the grid (export > import) on that phase.

    Rules:
      - Currents that are already negative (meter sends signed values,
        e.g. some Aidon firmwares) are left untouched, making the
        operation idempotent.
      - Per-phase directional powers (21/22, 41/42, 61/62) are preferred.
      - If a phase lacks both directional powers, the total registers
        (1.7.0 / 2.7.0) are used as a fallback.
      - Non-finite (NaN/inf) or non-numeric register values are ignored.
      - If no directional information is present in the telegram at all,
        nothing is changed.
    """
    total_imp = _finite_num(obis.get(_TOTAL_IMPORT))
    total_exp = _finite_num(obis.get(_TOTAL_EXPORT))

    for cur_code, (imp_code, exp_code) in _PHASE_MAP.items():
        val = _finite_num(obis.get(cur_code))
        if val is None or val <= 0:
            # absent, non-numeric, non-finite, zero, or already signed
            continue

        imp = _finite_num(obis.get(imp_code))
        exp = _finite_num(obis.get(exp_code))

        if imp is not None or exp is not None:
            imp_v = imp if imp is not None else 0.0
            exp_v = exp if exp is not None else 0.0
        elif total_imp is not None or total_exp is not None:
            imp_v = total_imp if total_imp is not None else 0.0
            exp_v = total_exp if total_exp is not None else 0.0
        else:
            continue  # no direction info in this telegram

        if exp_v > imp_v:
            obis[cur_code] = -val
