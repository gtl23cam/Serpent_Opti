
FAIL_TAGS = [
    "KEFF_BOL_TOO_LOW",
    # "KEFF_BOL_TOO_HIGH",
    "KEFF_2_3_TOO_LOW",
    "HFP_MTC_POSITIVE",
    "HFP_FTC_POSITIVE",
    "HZP_MTC_POSITIVE",
    "HZP_FTC_POSITIVE",
    "ROD_SUBCRIT_VIOLATED",
    "INSUFFICIENT_CRW",
    # "POWER_PEAKING_TOO_HIGH",
    "DNBR_TOO_LOW",
    "CENTERLINE_TEMP_TOO_HIGH",
]
def get_trial_failures(trial, constraints_fn):
    """Maps positive constraint violations to readable error tags."""
    g_vals = constraints_fn(trial,False)
    if len(g_vals) != len(FAIL_TAGS):
        raise ValueError(
            f"Dimension mismatch: constraints_fn returned {len(g_vals)} items, "
            f"but FAIL_TAGS has {len(FAIL_TAGS)} items."
        )
    return [tag for tag, g in zip(FAIL_TAGS, g_vals) if g > 0]