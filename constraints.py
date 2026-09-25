# CONSTRAINTS.py
import numpy as np
from evaluate_trial import DNBR_LIMIT, CENTERLINE_TEMP_LIMIT


def constraints(trial,output_dir,currently_optimising=True):
    """Evaluates non-dimensional output constraints for Joint Constrained TPE.

    Satisfied: g_i <= 0 | Violated: g_i > 0
    Normalized so that g_i = +1.0 represents a standard, significant violation.
    """
    NUM_CONSTRAINTS = 11

    # Absolute Physics Limits
    KEFF_BOL_MIN = 1.00
    KEFF_BOL_MAX = 1.15
    KEFF_2_3_MIN = 1.00
    ROD_SUBCRIT_LIMIT = 0.9
    MIN_CRW_LIMIT_PCM = 3000.0
    PIN_PEAKING_MAX = 1.4 



    # Normalization Scale Factors (Characteristic Violation Units)
    SCALE_KEFF = 0.05  # 5000 pcm k-eff offset = +1.0
    SCALE_MTC_D = 0.0020  # +200 pcm positive MTC delta = +1.0
    SCALE_FTC_D = 0.0010  # +100 pcm positive FTC delta = +1.0
    SCALE_CRW_PCM = 1000.0  # 1000 pcm CRW deficit = +1.0
    SCALE_FPIN = 0.10  # 0.1 peaking factor above limit = +1.0
    SCALE_DNBR = 0.10  # 0.1 DNBR below limit = +1.0
    SCALE_CENTERLINE_TEMP = 100.0  # 100°C above limit = +1.0


    keff_nom = trial.user_attrs.get("keff_steps_nom", [])
    bu_nom = trial.user_attrs.get("burnup_points", [])
    keff_bol = trial.user_attrs.get("keff_bol")
    n_branches = trial.user_attrs.get("n_branches", 0)
    branch_keff = trial.user_attrs.get("branch_keff") or {}

    # Safety guard for incomplete or pruned trials
    if keff_bol is None or not keff_nom:
        return [1.0] * NUM_CONSTRAINTS

    # 1. Core Keff Constraints
    g1_keff_bol_min = (KEFF_BOL_MIN - keff_bol) / SCALE_KEFF
    g2_keff_bol_max = (keff_bol - KEFF_BOL_MAX) / SCALE_KEFF

    # 2. Lifecycle 2/3 Keff Constraint

    if len(keff_nom) > 1:
        # 2/3 of the maximum burnup
        target_bu = (2 / 3) * bu_nom[-1]
        valid_indices = np.where(np.array(bu_nom) <= target_bu)[0]

        if valid_indices.size > 0:
            idx_2_3 = valid_indices[-1]
            keff_first_2_3 = keff_nom[: idx_2_3 + 1]
            print(keff_first_2_3)
            g3_keff_2_3 = (KEFF_2_3_MIN - min(keff_first_2_3)) / SCALE_KEFF
        else:
            print("g3 not eval")
            g3_keff_2_3 = -1.0
    else:
        print("g3 not eval")
        g3_keff_2_3 = -1.0

    # Default all branch constraints to inactive/satisfied (-1.0)

    g4_hfp_mtc_max = -1.0
    g5_hfp_ftc_max = -1.0
    g6_hzp_mtc_max = -1.0
    g7_hzp_ftc_max = -1.0
    g8_rodded_subcrit_max = -1.0
    g9_crw_min = -1.0
    g10_fpin_nom = -1.0
    g11_DNBR = -1.0

    # 3. Dynamic Branch Constraints Evaluation
    if n_branches > 0 and branch_keff:
        hfp_mtc = branch_keff.get("hfp_mtc", [])
        # hfp_ftc = branch_keff.get("hfp_ftc", [])
        hzp_base = branch_keff.get("hzp_base", [])
        hzp_mtc = branch_keff.get("hzp_mtc", [])
        # hzp_ftc = branch_keff.get("hzp_ftc", [])
        rod_steps = branch_keff.get("rodIn_cold", [])

        # HFP MTC: Delta k between temperature increase and nominal
        if hfp_mtc and len(hfp_mtc) == len(keff_nom):
            g4_hfp_mtc_max = (
                max(k_m - k_n for k_m, k_n in zip(hfp_mtc, keff_nom))
                / SCALE_MTC_D
            )

        # # HFP FTC: Delta k between fuel heating and nominal
        # if hfp_ftc and len(hfp_ftc) == len(keff_nom):
        #     g5_hfp_ftc_max = (
        #         max(k_f - k_n for k_f, k_n in zip(hfp_ftc, keff_nom))
        #         / SCALE_FTC_DK
        #     )

        # HZP MTC: Delta k relative to HZP base
        if hzp_mtc and hzp_base and len(hzp_mtc) == len(hzp_base):
            g6_hzp_mtc_max = (
                max(k_m - k_b for k_m, k_b in zip(hzp_mtc, hzp_base))
                / SCALE_MTC_D
            )

        # # HZP FTC: Delta k relative to HZP base
        # if hzp_ftc and hzp_base and len(hzp_ftc) == len(hzp_base):
        #     g7_hzp_ftc_max = (
        #         max(k_f - k_b for k_f, k_b in zip(hzp_ftc, hzp_base))
        #         / SCALE_FTC_DK
        #     )

        # Rodded Subcriticality: Maximum k-eff when control rods are inserted
        if rod_steps:
            g8_rodded_subcrit_max = (
                max(k_r - ROD_SUBCRIT_LIMIT for k_r in rod_steps) / SCALE_KEFF
            )

        # Control Rod Worth: Minimum reactivity worth in pcm vs required limit
        if rod_steps and len(rod_steps) == len(keff_nom):
            crw_pcm = [
                (((k_n - k_r) / (k_n * k_r)) * 1e5)
                for k_n, k_r in zip(keff_nom, rod_steps)
            ]
            g9_crw_min = (MIN_CRW_LIMIT_PCM - min(crw_pcm)) / SCALE_CRW_PCM

    #power peaking factor on nominal case
    fpin_nom = (trial.user_attrs.get("fpin_by_branch") or {}).get("nominal")
    g10_fpin_nom = (fpin_nom - PIN_PEAKING_MAX) / SCALE_FPIN if fpin_nom is not None else -1.0


    actual_linear_assem_power = trial.user_attrs.get("linear_power")
    dnbr = trial.user_attrs.get("DNBR")
    cent_temp = trial.user_attrs.get("Temp_cent")
    valid_N_sa = trial.user_attrs.get("N_sa")


    est_linear_assem_power = trial.user_attrs.get("estimated_power")
    est_dnbr = trial.user_attrs.get("estimated_DNBR")
    est_max_centerline_temp = trial.user_attrs.get("estimated_T_centerline_max")
    est_N_sa = trial.user_attrs.get("estimated_N_sa")

    if valid_N_sa is None:
        g11_DNBR = 1.0  # Significant violation
        g12_centerline_temp = 1.0  # Significant violation
        log_entry = (f"Trial {trial.number} no real valid N_sa found.\n")
    else:
        g11_DNBR = (DNBR_LIMIT - dnbr) / SCALE_DNBR  # type: ignore
        g12_centerline_temp = (cent_temp - CENTERLINE_TEMP_LIMIT) / SCALE_CENTERLINE_TEMP # type: ignore
        diff_pct = ((actual_linear_assem_power - est_linear_assem_power) / est_linear_assem_power) * 100.0

        log_entry = (
            f"Trial {trial.number}:\n Actual Power={actual_linear_assem_power:.4f} kW/m, Estimated Power={est_linear_assem_power:.4f} kW/m, Diff={diff_pct:+.2f}%\n Actual DNBR={dnbr:.4f}, Estimated DNBR={est_dnbr:.4f}\n Actual Max Centerline Temp={cent_temp:.2f} °C, Estimated Max Centerline Temp={est_max_centerline_temp:.2f} °C\n Valid N_sa={valid_N_sa}, Estimated N_sa={est_N_sa}\n Calculated F rad={fpin_nom},  Preliminary F rad={1.4:.2f}"
        )
    if currently_optimising:
        with open(output_dir/"TH_estimate_accuracy.txt", "a") as f:
                f.write(log_entry)

    return [
        g1_keff_bol_min,
        g2_keff_bol_max,
        g3_keff_2_3,
        g4_hfp_mtc_max,
        g5_hfp_ftc_max,
        g6_hzp_mtc_max,
        g7_hzp_ftc_max,
        g8_rodded_subcrit_max,
        g9_crw_min,
        # g10_fpin_nom,
        g11_DNBR,
        g12_centerline_temp,
    ]
