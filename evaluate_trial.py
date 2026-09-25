import numpy as np
import optuna

# Custom project modules
from utils import (
    Detector,
    BurnupSettings,
    RunSettings,
    BranchingSettings,
    build_rows_from_partitioned_latice,
    get_partitioned_lattice_coords,
    build_geometry17x17,
    sample_guide_and_gd,
    sample_guide_and_gd_bi,
    build_case,
    thermal_hydraulic_estimate,
    wrapped_sss2,
    branch_peaking_summary,
    max_fpin_by_branch,
    calculate_fuel_cost,
)

DNBR_LIMIT = 1.3
CENTERLINE_TEMP_LIMIT = 2400
"""These 2 are same as in the constraints evaluaton, as that is where the constraint is actually evaluated. 
The TH code is ran on the live trial, once before serpent is ran and once after, so we need the limits here too to 
attempt to build a feasible reactor in both cases. If the suggested geometry never finds on a feasible reactor 
(iterateds through to 240 assemblies and still doesnt satisfy limits) before running serpent, the trial is pruned. 
If initially a TH feasible solution was found, and then after the serpent run it can no longer be found (because f rad is too high), 
the last values (so e.g. num of assemblies at the maximum of the TH codes range) from the TH sizing calc are passed to the constraints evaluation, 
but we will already know those constraints will be failed. This case is very rare, and unlikely to be good anyway due to the corresponding reactor size"""

T_FUEL = 950
RUN_SETTINGS = RunSettings(
    tfuel=T_FUEL,
    power=20400,
    bc=2,
    pop="10000 20 15",
    extra_settings=["set gcu -1", "set cmm 0", "set opti 1"],
)

DETECTORS = [
    Detector("det pinpowers dr -8 void dx -10.752 10.752 17 dy -10.752 10.752 17")
]

BURNUP_SETTINGS = BurnupSettings(
    enabled=True,
    branching=True,
    points=[0.1, 0.5, 1, 2, 4, 7, 10, 13, 18, 22, 28, 38, 47, 60],
    div_lines=[
        "div fuelNoGad  sep 1",
        "div fuelYesGad sep 1 subr 5 0.0 0.5525",
    ],
    mcvol=10_000_000,
    inventory="all",
    pcc="le 10",
    declib="/home/gtl23/XSdata_jeff311/sss_jeff311.dec",
    nfylib="/home/gtl23/XSdata_jeff311/sss_jeff311.nfy",
    egrid="5e-5 1e-9 15.0",
)

BRANCHING_SETTINGS = BranchingSettings(
    absorber_name="B4C",
    has_gad=True,
    coef_points=[0, 4, 7, 18, 28, 38, 60],
    t_hfp_fuel=T_FUEL,
    t_hot_cool=583.0,
    t_cold_SD=300,  # make 300 - needs new fuel libraries generating
    rho_hot_cool=-0.70602,
    rho_cold_cool=-0.9965,  # adjust accordingly
    dt_ftc=30.0,
    dt_mtc=25.0,
    rho_hot_mtc=-0.6350,
    sab_hot_pair=("lwj3.11t", "lwj3.13t"),
    sab_cold_pair=("lwj3.00t", "lwj3.05t"),
)




def create_and_evaluate(
    trial: optuna.Trial,
    shared_cache,
    total_eval_requests,
    sss2_run_count,
    output_dir,
) -> float:

    # Standard fuel enrichment is ALWAYS sampled (applies to standard pins)
    f_enr_raw = trial.suggest_float("fuel_enrichment", 0.0, 6.0, step=0.05)
    f_enr = float(np.round(f_enr_raw, 4))

    fuel_radius = trial.suggest_float("fuel_radius", 0.35, 0.54, step=0.01)
    fuel_radii = [fuel_radius, fuel_radius + 0.00654, fuel_radius + 0.047914]

    ## Geometry sampling done here
    axis_coords, interior_coords = get_partitioned_lattice_coords()
    gt_axis_idx, gt_interior_idx, gd_axis_idx, gd_interior_idx = sample_guide_and_gd_bi(
        trial, axis_coords, interior_coords, max_gd_picks=4, max_gt_picks=4)
    total_guide_tubes = (len(gt_axis_idx) * 4) + (len(gt_interior_idx) * 8)
    total_assembly_gd_pins = (len(gd_axis_idx) * 4) + (len(gd_interior_idx) * 8)
    rows = build_rows_from_partitioned_latice(
        gt_axis_idx, gt_interior_idx, gd_axis_idx, gd_interior_idx
    )

    gt_ax_str = "_".join(f"{axis_coords[i]}".replace(" ", "") for i in gt_axis_idx)
    gt_int_str = "_".join(f"{interior_coords[i]}".replace(" ", "") for i in gt_interior_idx)
    gd_ax_str = "_".join(f"{axis_coords[i]}".replace(" ", "") for i in gd_axis_idx)
    gd_int_str = "_".join(f"{interior_coords[i]}".replace(" ", "") for i in gd_interior_idx)

    geo_name = (
        f"geo_gd{total_assembly_gd_pins}_{gd_ax_str}_{gd_int_str}"
        f"_gt{total_guide_tubes}_{gt_ax_str}_{gt_int_str}"
    )

    if total_assembly_gd_pins > 0:
        gd_conc_raw = trial.suggest_float("gd_conc", 0.1, 12.0, step=0.1)  # dont need to sample 0.0 as this would be a physically identical case to having no gd pins in assembly which is reachable through the geometric sampling
        gd_conc = float(round(gd_conc_raw, 4))  ##rounded to remove floating point noise
        g_enr = trial.suggest_float("gad_enrichment", 0.7, 2.0, step=0.025)
        g_enr = float(round(g_enr, 4))
    else:
        gd_conc = 0.0
        g_enr = 0.0

    has_gad = total_assembly_gd_pins > 0

    geo_var = build_geometry17x17(geo_name, rows, has_gad=has_gad, fuel_radii=fuel_radii)

    ## write parameters needed for thermal hydraulic analysis to trial attributes for later use
    trial.set_user_attr("total_guide_tubes", total_guide_tubes)
    trial.set_user_attr("total_pins", 17**2)
    trial.set_user_attr("total_gad_pins", total_assembly_gd_pins)
    trial.set_user_attr("pitch", geo_var.lattice.pitch / 100)  # convert from cm to m for TH analysis
    trial.set_user_attr("fuel_radii", fuel_radii)

    with total_eval_requests.get_lock():
        total_eval_requests.value += 1

    cache_key = (
        round(f_enr, 3),
        round(g_enr, 3),
        round(gd_conc, 3),
        round(fuel_radius, 3),
        geo_var.name,
    )

    if cache_key in shared_cache:
        # Tag trial as a cache hit in Optuna's database
        trial.set_user_attr("is_cache_hit", True)
        trial.set_user_attr("cache_key", cache_key)

        cached_val = shared_cache[cache_key]
        if cached_val == "PRUNED":
            print(f"[CACHE HIT - PRUNED] {cache_key}")
            raise optuna.TrialPruned()

        print(f"[CACHE HIT - COMPLETED] {cache_key}")
        for step_idx, keff in enumerate(cached_val["keff"]):
            trial.report(float(keff), step=step_idx)
        return cached_val

    # Explicitly tag cache misses
    trial.set_user_attr("is_cache_hit", False)
    trial.set_user_attr("cache_key", cache_key)

    with sss2_run_count.get_lock():
        sss2_run_count.value += 1
        current_run_id = sss2_run_count.value

    # Estimate the power to update the run settings using the thermal hydraulic analysis
    (
        dnbr_estimate,
        T_centerline_max_estimate,
        power_estimate,
        N_sa_estimate,
        r_core,
        h_core,
    ) = thermal_hydraulic_estimate(
        trial, f_rad=1.4, min_DNBR_target=DNBR_LIMIT, max_T_centerline_target=CENTERLINE_TEMP_LIMIT
    )

    RUN_SETTINGS.power = power_estimate
    trial.set_user_attr("estimated_power", power_estimate)
    trial.set_user_attr("estimated_DNBR", dnbr_estimate)
    trial.set_user_attr("estimated_T_centerline_max", T_centerline_max_estimate)
    trial.set_user_attr("estimated_N_sa", N_sa_estimate)
    trial.set_user_attr("estimated_H_core", h_core)

    case = build_case(
        geometry_name=geo_var.name,
        absorber_name="B4C",
        fuel_enrichment=f_enr,
        gad_enrichment=g_enr,
        gd_conc=gd_conc,
        detectors=DETECTORS,
        run_settings=RUN_SETTINGS,
        burnup_settings=BURNUP_SETTINGS,
        iteration=trial.number,
        branching_settings=BRANCHING_SETTINGS,
        geometry=geo_var,
    )
    print(
        f"[Trial #{trial.number} Serpent Run #{current_run_id}] Evaluating: {cache_key}"
    )

    ### execute serpent, or return a serpent run from cache, if these exact parameters have been ran before
    try:
        result = wrapped_sss2(case=case, output_dir=output_dir, trial=trial)
        result["case_name"] = case.case_name
        shared_cache[cache_key] = result
    except optuna.TrialPruned:
        shared_cache[cache_key] = "PRUNED"
        raise

    ### save the results
    keff_steps = result["keff"]
    branch_keff = result.get("branch_keff", {})
    trial.set_user_attr("keff_steps_nom", keff_steps)
    trial.set_user_attr("keff_bol", float(keff_steps[0]))
    trial.set_user_attr("keff_eol", float(keff_steps[-1]))
    trial.set_user_attr("burn_days", result["burn_days"])
    trial.set_user_attr("burnup_points", result["burnup_points"])
    trial.set_user_attr("n_branches", result["n_branches"])
    trial.set_user_attr("geo_name", geo_name)
    trial.set_user_attr("branch_keff", branch_keff)

    # Detector Output Processing including Thermal Hydraulics
    peaking_df = branch_peaking_summary(case_dir=output_dir / result["case_name"], branch_order=result["branch_order"])
    fpin_by_branch = max_fpin_by_branch(peaking_df)
    fpin_nom = fpin_by_branch.get("nominal")
    dnbr, cent_temp, actual_linear_assem_power, valid_N_sa, r_core, h_core = thermal_hydraulic_estimate(trial, f_rad=fpin_nom, min_DNBR_target=DNBR_LIMIT, max_T_centerline_target=CENTERLINE_TEMP_LIMIT, finished = True)  # type: ignore
    trial.set_user_attr("DNBR", dnbr)
    trial.set_user_attr("Temp_cent", cent_temp)
    trial.set_user_attr("N_sa", valid_N_sa)
    trial.set_user_attr("linear_power", actual_linear_assem_power)
    trial.set_user_attr("fpin_by_branch", fpin_by_branch)
    trial.set_user_attr("fpin_max_overall", max(fpin_by_branch.values()) if fpin_by_branch else None)

    cost_data = calculate_fuel_cost(
        h_core=h_core,
        fuel_radius=fuel_radius,
        gd_conc=gd_conc,
        total_assembly_gd_pins=total_assembly_gd_pins,
        total_guide_tubes=total_guide_tubes,
        valid_N_sa=valid_N_sa,
        f_enr=f_enr,
        has_gad=has_gad,
        g_enr=g_enr,  # Or pass g_enr if available, defaults to 0.0
    )

    total_fuel_cost = cost_data["total_fuel_cost"]
    total_fuel_u_mass = cost_data["total_fuel_u_mass"]
    return total_fuel_cost
