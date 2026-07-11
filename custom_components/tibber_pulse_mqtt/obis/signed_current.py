from __future__ import annotations

from typing import Any, Dict

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


def apply_signed_current(obis: Dict[str, Any]) -> None:
    """
    Mutate *obis* in place: negate phase-current values while power flows
    towards the grid (export > import) on that phase.

    Rules:
      - Currents that are already negative (meter sends signed values,
        e.g. some Aidon firmwares) are left untouched.
      - Per-phase directional powers (21/22, 41/42, 61/62) are preferred.
      - If a phase lacks both directional powers, the total registers
        (1.7.0 / 2.7.0) are used as a fallback.
      - If no directional information is present in the telegram at all,
        nothing is changed.
    """
    total_imp = obis.get(_TOTAL_IMPORT)
    total_exp = obis.get(_TOTAL_EXPORT)

    for cur_code, (imp_code, exp_code) in _PHASE_MAP.items():
        val = obis.get(cur_code)
        if not isinstance(val, (int, float)) or val <= 0:
            # absent, non-numeric, zero, or already signed by the meter
            continue

        imp = obis.get(imp_code)
        exp = obis.get(exp_code)

        if isinstance(imp, (int, float)) or isinstance(exp, (int, float)):
            imp_v = imp if isinstance(imp, (int, float)) else 0.0
            exp_v = exp if isinstance(exp, (int, float)) else 0.0
        elif isinstance(total_imp, (int, float)) or isinstance(total_exp, (int, float)):
            imp_v = total_imp if isinstance(total_imp, (int, float)) else 0.0
            exp_v = total_exp if isinstance(total_exp, (int, float)) else 0.0
        else:
            continue  # no direction info in this telegram

        if exp_v > imp_v:
            obis[cur_code] = -val
