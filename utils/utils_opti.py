import os
import subprocess
from pathlib import Path
from serpentTools.settings import rc
import re
from typing import Dict, List, Sequence
# pyright: reportAttributeAccessIssue=false
import numpy as np
from scipy.optimize import minimize_scalar
import pandas as pd
import serpentTools as st
import psutil
from functools import wraps
import time
import optuna
rc["serpentVersion"] = "2.1.32"


from .case_rendering import render_main_input, parse_branches_inc, render_branches

SERPENT_CMD = os.path.expandvars("$HOME/compile.2.1.32/sss2")
OMP_THREADS = "7"  # OpenMP threads assigned per case, should ideally match number in main

_DET_FILE_RE = re.compile(r"det(\d+)(?:_?b(\d+))?\.m$", re.IGNORECASE) # Supports both det1b1.m and det1_b1.m formats



def run_case_monitored(inp_path, trial, n_nominal_steps):
    """Spawns Serpent and polls nominal burnup steps for live pruning."""
    res_path = inp_path.parent / f"{inp_path.name}_res.m"
    log_file = inp_path.parent / f"{inp_path.stem}.log"

    # Dynamically read OMP_NUM_THREADS set by @allocate_cores 
    omp_threads = os.environ.get("OMP_NUM_THREADS", str(len(psutil.Process().cpu_affinity())))

    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = omp_threads
    cmd = [SERPENT_CMD, "-omp", omp_threads, inp_path.name]

    with open(log_file, "w") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=inp_path.parent,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        parsed_steps = 0

        while proc.poll() is None:
            time.sleep(10)
            if not res_path.exists():
                continue

            # 1. Safely parse file (ONLY catch file read/parsing errors)
            keff_data = None
            try:
                res = st.read(str(res_path))
                keff_data = res.resdata.get("absKeff")
            except Exception:
                continue  # Ignore transient parsing errors while Serpent writes

            if keff_data is None:
                continue

            nominal_keff = (
                keff_data[:n_nominal_steps, 0]
                if keff_data.ndim > 1
                else [float(keff_data[0])]
            )

            # 2. Check pruning constraints outside the try-except block
            while (
                parsed_steps < len(nominal_keff)
                and parsed_steps < n_nominal_steps
            ):
                current_keff = float(nominal_keff[parsed_steps])
                # trial.report(current_keff, step=parsed_steps)

                # Step 0 (BOL) nominal check
                if parsed_steps == 0:
                    trial.set_user_attr("keff_bol", current_keff)
                    if not (0.95 <= current_keff <= 1.9):
                        print(
                            f"[PRUNED BOL] {inp_path.name} | keff = {current_keff:.5f}"
                        )
                        proc.kill()
                        raise optuna.TrialPruned()

                # Step 1+ nominal burnup check
                elif 0<parsed_steps<3  and current_keff < 0.9:
                    print(
                        f"[PRUNED STEP {parsed_steps}] {inp_path.name} | keff = {current_keff:.5f}"
                    )
                    proc.kill()
                    raise optuna.TrialPruned()

                parsed_steps += 1

        proc.wait()

    # 3. Handle actual unexpected Serpent crashes
    if proc.returncode != 0:
        print(f"[ERROR] {inp_path.name} failed (See {log_file.name})")
        raise optuna.TrialPruned(f"Serpent exited with code {proc.returncode}. This was optuna trial{trial.number}")
    return ""

def fetch_full_results(inp_path: Path, n_nominal_steps: int):
    """Parses nominal burnup results and optional branch data from completed run."""
    res_path = inp_path.with_name(inp_path.name + "_res.m")
    branches_path = inp_path.with_name(inp_path.name + "_branches.inc")

    # Guard against Serpent crashes / missing output files
    if not res_path.exists():
        print(f"[SERPENT CRASH] Result file missing: {res_path}. Pruning trial.")
        raise optuna.TrialPruned()

    res = st.read(str(res_path))

        # 1. Extract raw arrays from resdata
    keff_raw = res.resdata["absKeff"]
    keff_all = keff_raw if keff_raw.ndim == 1 else keff_raw[:, 0]


    burn_days_raw = res.resdata["burnDays"]
    burn_days_all = (
        burn_days_raw if burn_days_raw.ndim == 1 else burn_days_raw[:, 0]
    )

    burnup_raw = res.resdata["burnup"]
    burnup_all = burnup_raw if burnup_raw.ndim == 1 else burnup_raw[:, 0]

    # 2. Slice nominal depletion steps
    nominal_keff_steps = [float(k) for k in keff_all[:n_nominal_steps]]
    burn_days = [float(d) for d in burn_days_all[:n_nominal_steps]]
    burnup_points = [float(b) for b in burnup_all[:n_nominal_steps]]

    # 3. Process branches if file exists
    if branches_path.exists():
        branch_info = parse_branches_inc(branches_path)
        branch_keff_dict = {}

        if len(keff_all) > 0 and branch_info["n_branches"] > 0:
            for i, b_name in enumerate(branch_info["branch_order"]):
                start_idx = i * n_nominal_steps
                end_idx = start_idx + n_nominal_steps
                branch_keff_dict[b_name] = [
                    float(k) for k in keff_all[start_idx:end_idx]
                ]

        return {
            "keff": nominal_keff_steps,
            "eol_keff": nominal_keff_steps[-1] if nominal_keff_steps else None,
            "burn_days": burn_days,
            "branch_keff": branch_keff_dict,
            **branch_info,
        }

    # Fallback for non-branching runs
    return {
        "keff": nominal_keff_steps,
        "eol_keff": nominal_keff_steps[-1] if nominal_keff_steps else None,
        "burn_days": burn_days,
        "burnup_points": burnup_points,
        "n_burnup": len(burnup_points),
        "n_branches": 0,
        "branch_order": [],
        "branch_keff": {},
    }


def wrapped_sss2(case, output_dir, trial):
    """Executes monitored case using exact nominal step count."""
    output_dir = Path(output_dir)
    case_dir = output_dir / case.case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    inp_path = case_dir / case.case_name
    branch_path = case_dir / (case_dir.name +"_branches.inc") 

    main_text = render_main_input(case)
    #need to write branch file too
    branch_text = render_branches(case)
    inp_path.write_text(main_text, encoding="ascii")
    branch_path.write_text(branch_text, encoding="ascii")


    # Number of nominal burnup points (e.g., 8)
    branch_settings = getattr(case, "branching_settings", None)
    points = branch_settings.coef_points if branch_settings else []

    if len(points) > 1:
        n_nominal_steps = len(points)
    else:
        n_nominal_steps = 1  # Default single BOL state stepp
        print("1 nonminal step")

    status = run_case_monitored(inp_path, trial, n_nominal_steps=n_nominal_steps)
    print(status)

    return fetch_full_results(inp_path, n_nominal_steps=n_nominal_steps)

def read_pin_powers(
    det_file: Path, det_name: str = "pinpowers"
) -> pd.DataFrame:
  det_data = st.read(str(det_file), reader="det")
  if det_name not in det_data.detectors:
    raise KeyError(
        f"Detector '{det_name}' not found in {det_file.name}. "
        f"Available: {list(det_data.detectors.keys())}"
    )
  detector = det_data.detectors[det_name]
  tallies = detector.tallies
  idx = np.indices(tallies.shape)

  data = {f"dim{i}_idx": idx[i].ravel() for i in range(tallies.ndim)}
  data["power"] = tallies.ravel()
  return pd.DataFrame(data)


def pin_peaking_factor(
    df: pd.DataFrame, zero_threshold: float = 1e-12
) -> float:
  """F_pin = P_max / P_avg over active (non-zero) pin positions."""
  idx_cols = [c for c in df.columns if c.endswith("_idx")]
  pin_powers = (
      df.groupby(idx_cols)["power"].sum() if idx_cols else df["power"]
  )
  active = pin_powers[pin_powers > zero_threshold]
  if active.empty:
    raise ValueError("No positive pin powers above zero_threshold.")
  return float(active.max() / active.mean())


def discover_detector_files(
    case_dir: Path, branch_order: Sequence[str]
) -> List[Dict]:
  entries = []
  for f in Path(case_dir).glob("*_det*.m"):
    if f.name.endswith("_dep.m"):
      continue
    match = _DET_FILE_RE.search(f.name)
    if not match:
      continue
    step = int(match.group(1))
    b_str = match.group(2)
    if b_str is None:
      branch = "base"  # Nominal depletion step
    else:
      b_num = int(b_str)
      branch = (
          branch_order[b_num - 1]
          if b_num - 1 < len(branch_order)
          else f"branch_{b_num}"
      )
    entries.append({"file": f, "step": step, "branch": branch})

  return sorted(entries, key=lambda e: (e["step"], e["branch"]))


def branch_peaking_summary(
    case_dir: Path, branch_order: Sequence[str], det_name: str = "pinpowers"
) -> pd.DataFrame:
  """F_pin for every (step, branch) detector file found in a case directory."""
  rows = []
  for entry in discover_detector_files(case_dir, branch_order):
    try:
      df = read_pin_powers(entry["file"], det_name)
      rows.append({
          "step": entry["step"],
          "branch": entry["branch"],
          "F_pin": pin_peaking_factor(df),
      })
    except Exception as e:
      print(f"[SKIP] {entry['file'].name}: {e}")
  return pd.DataFrame(rows)


def max_fpin_by_branch(summary_df: pd.DataFrame) -> Dict[str, float]:
  """Peak F_pin per branch across all available burnup/coef points."""
  if summary_df.empty or "branch" not in summary_df.columns:
    return {}
  return summary_df.groupby("branch")["F_pin"].max().to_dict() # type: ignore



def calculate_fuel_cost(
    h_core: float,
    fuel_radius: float,
    gd_conc: float,
    total_assembly_gd_pins: int,
    total_guide_tubes: int,
    valid_N_sa: int,
    f_enr: float,
    has_gad: bool,
    g_enr: float = 0.0,
) -> dict:
    """
    Computes fuel/Gd feed + separative work cost without altering underlying math.
    Returns a dictionary with total_fuel_cost and individual mass/SWU metrics.
    """
    RHO_UO2 = 10.4  # g/cm^3, effective UO2 density
    U_FRAC_IN_UO2 = 238.03 / (238.03 + 2 * 16.00)  # U mass fraction in UO2, ~0.881
    GAD_PIN_RADIUS = 0.3  # cm, fixed for all Gd pins

    core_height_cm = h_core * 100

    fuel_pin_volume = np.pi * fuel_radius**2 * core_height_cm  
    fuel_pin_uo2_mass = fuel_pin_volume * RHO_UO2
    fuel_pin_u_mass = fuel_pin_uo2_mass * U_FRAC_IN_UO2

    gad_pin_volume = np.pi * GAD_PIN_RADIUS**2 * core_height_cm # type: ignore
    gad_pin_uo2_mass = gad_pin_volume * RHO_UO2 * (1 - gd_conc / 100)
    gad_pin_u_mass = gad_pin_uo2_mass * U_FRAC_IN_UO2

    n_fuel_pins = 17**2 - total_assembly_gd_pins - total_guide_tubes - 1

    total_fuel_u_mass = valid_N_sa * n_fuel_pins * fuel_pin_u_mass
    total_gad_u_mass = valid_N_sa * total_assembly_gd_pins * gad_pin_u_mass

    # --- Fuel cost proxy: uranium feed + separative work ---
    def cost_for_tails(xw, P, xp, xf, c_feed, c_swu):
        F = P * (xp - xw) / (xf - xw)
        W = F - P
        swu = (
            P * (1 - 2 * xp) * np.log((1 - xp) / xp)
            + W * (1 - 2 * xw) * np.log((1 - xw) / xw)
            - F * (1 - 2 * xf) * np.log((1 - xf) / xf)
        )
        return c_feed * F + c_swu * swu

    x_f = 0.00711  # natural feed enrich, tails enrich
    c_feed, c_swu, c_fab = 230, 109, 300  # $/kgU feed, $/SWU, $/kgU fabrication

    P_fuel = total_fuel_u_mass / 1000  # kgU
    xp_fuel = f_enr / 100
    x_w = minimize_scalar(
        cost_for_tails,
        bounds=(1e-4, x_f - 1e-4),
        method="bounded",
        args=(P_fuel, xp_fuel, x_f, c_feed, c_swu),
    ).x  # type: ignore

    F_fuel = P_fuel * (xp_fuel - x_w) / (x_f - x_w)
    W_fuel = F_fuel - P_fuel
    swu_fuel = (
        P_fuel * (1 - 2 * xp_fuel) * np.log((1 - xp_fuel) / xp_fuel)
        + W_fuel * (1 - 2 * x_w) * np.log((1 - x_w) / x_w) 
        - F_fuel * (1 - 2 * x_f) * np.log((1 - x_f) / x_f)
    )

    if has_gad:
        P_gad = total_gad_u_mass / 1000
        xp_gad = g_enr / 100
        F_gad = P_gad * (xp_gad - x_w) / (x_f - x_w)
        W_gad = F_gad - P_gad
        swu_gad = (
            P_gad * (1 - 2 * xp_gad) * np.log((1 - xp_gad) / xp_gad)
            + W_gad * (1 - 2 * x_w) * np.log((1 - x_w) / x_w)
            - F_gad * (1 - 2 * x_f) * np.log((1 - x_f) / x_f)
        )
    else:
        P_gad = F_gad = swu_gad = 0.0

    total_feed_mass = F_fuel + F_gad
    total_swu = swu_fuel + swu_gad
    total_fuel_cost = (
        c_feed * total_feed_mass + c_swu * total_swu + c_fab * (P_fuel + P_gad)
    )

    return {
        "total_fuel_cost": total_fuel_cost,
        "total_feed_mass": total_feed_mass,
        "total_swu": total_swu,
        "total_fuel_u_mass": total_fuel_u_mass,
        "total_gad_u_mass": total_gad_u_mass,
    }
