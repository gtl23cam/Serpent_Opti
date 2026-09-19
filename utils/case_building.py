from __future__ import annotations
from typing import Optional

from .utils_geom import Geometry
from .utils_fuels import (
    common_materials,
    common_therm,
    resolve_fuels,
    ABSORBER_VARIANTS,
)
from .serpent_objects import Branch, BranchDirective, CoefCard, RunCase, BranchingSettings

"""This script builds the runcase object which can then be written to the input and branch files. 
case_building consists of the build case function which collates all the run and burnup settings, geometry and handles fuel imports, and additionallly a branch building script. 
build_case is called by wrapped_sss2 and the output is used by the rendering scripts to create the 2 files
    """

def build_branches(
    settings: BranchingSettings,
    burnup_enabled: bool = True,
) -> tuple[list[Branch], CoefCard]:
    """Uses the branching settings to create all the different branch objects and coef card needed to render the branches.inc file

    Args:
        settings (BranchingSettings): object containg all the branching settings
        burnup_enabled (bool, optional): flag to track if serpent will be running any burnup. Defaults to True.

    Returns:
        tuple[list[Branch], CoefCard]: List of the branch objects and the coef card object
    """

    burnup_points = settings.coef_points
    h_low, h_high = settings.sab_hot_pair
    c_low, c_high = settings.sab_cold_pair

    # Paired fuel material maps (nominal 900K -> cold 300K base)
    fuel_mats = ["fuelNoGad"] + (["fuelYesGad"] if settings.has_gad else [])
    fuel_cold_mats = ["fuelNoGad_cold"] + (
        ["fuelYesGad_cold"] if settings.has_gad else []
    )

    fuel_pairs = list(zip(fuel_mats, fuel_cold_mats))
    # Dynamic target calculations
    t_hfp_ftc = settings.t_hfp_fuel + settings.dt_ftc
    t_hot_mtc = settings.t_hot_cool + settings.dt_mtc
    t_hzp_ftc = settings.t_hot_cool + settings.dt_ftc

    fuel_density = -10.307

    branches = [
        # HOT FULL POWER (HFP) BRANCHES
        Branch(
            name="nominal",
            comment=f"HFP Unrodded Base ({settings.t_hfp_fuel:.0f}K Fuel / {settings.t_hot_cool:.0f}K Cool)",
        ),
        # Branch(
        #     name="rodIn_hot",
        #     comment="HFP Control Rod Insertion",
        #     directives=[
        #         BranchDirective(f"repm water_GT {settings.absorber_name}"),
                # BranchDirective(f"xenon 0"),

        #     ],
        # ),
        # Branch(
        #     name="hfp_ftc",
        #     comment=f"HFP FTC (+{int(settings.dt_ftc)}K fuel -> {t_hfp_ftc:.1f}K)",
        #     directives=[
        #         BranchDirective(f"stp {m} {fuel_density} {t_hfp_ftc:.1f}")
        #         for m in fuel_mats
        #     ]
        #     + [BranchDirective(f"var TFU {int(t_hfp_ftc)}")],
        # ),
        Branch(
            name="hfp_mtc",
            comment=f"HFP MTC (+{int(settings.dt_mtc)}K coolant -> {t_hot_mtc:.1f}K)",
            directives=[
                BranchDirective(
                    f"stp water {settings.rho_hot_mtc:.5f} {t_hot_mtc:.1f} lwtr {h_low} {h_high}"
                ),
                BranchDirective(
                    f"stp water_GT {settings.rho_hot_mtc:.5f} {t_hot_mtc:.1f} lwtr"
                    f" {h_low} {h_high}"
                ),
                BranchDirective(f"var TCO {int(t_hot_mtc)}"),
            ],
        ),
        # HOT ZERO POWER (HZP) BRANCHES (Swaps to _cold mats, broadens to 580K)
        Branch(
            name="hzp_base",
            comment=(
                f"HZP Base: Swaps fuel to _cold mats and broadens to"
                f" {settings.t_hot_cool:.0f} K with no xenon"
            ),
            directives=[
                *[BranchDirective(f"repm {m} {m_cold}") for m, m_cold in fuel_pairs],
                *[
                    BranchDirective(
                        f"stp {m} {fuel_density} {settings.t_hot_cool:.1f}"
                    )
                    for m, _ in fuel_pairs  # Targeted original name 'm'
                ],
                BranchDirective(f"xenon 0"),
                BranchDirective(f"var TFU {int(settings.t_hot_cool)}"),
            ],
        ),
        # Branch(
        #     name="hzp_ftc",
        #     comment=(
        #         f"HZP FTC (+{int(settings.dt_ftc)}K fuel off 580K base ->"
        #         f" {t_hzp_ftc:.1f}K with no xenon)"
        #     ),
        #     directives=[
        #         *[BranchDirective(f"repm {m} {m_cold}") for m, m_cold in fuel_pairs],
        #         *[
        #             BranchDirective(f"stp {m} {fuel_density} {t_hzp_ftc:.1f}")
        #             for m, _ in fuel_pairs  
        #         ],
        #         BranchDirective(f"xenon 0"),
        #         BranchDirective(f"var TFU {int(t_hzp_ftc)}"),
        #     ],
        # ),
        Branch(
            name="hzp_mtc",
            comment=(
                f"HZP MTC (+{int(settings.dt_mtc)}K coolant -> {t_hot_mtc:.1f}K, fuel at"
                " 580K base with no xenon)"
            ),
            directives=[
                *[BranchDirective(f"repm {m} {m_cold}") for m, m_cold in fuel_pairs],
                *[
                    BranchDirective(
                        f"stp {m} {fuel_density} {settings.t_hot_cool:.1f}"
                    )
                    for m, _ in fuel_pairs  # Targeting original name 'm'
                ],
                BranchDirective(
                    f"stp water {settings.rho_hot_mtc:.5f} {t_hot_mtc:.1f} lwtr"
                    f" {h_low} {h_high}"
                ),
                BranchDirective(
                    f"stp water_GT {settings.rho_hot_mtc:.5f} {t_hot_mtc:.1f} lwtr"
                    f" {h_low} {h_high}"
                ),
                BranchDirective(f"xenon 0"),
                BranchDirective(f"var TFU {int(settings.t_hot_cool)}"),
                BranchDirective(f"var TCO {int(t_hot_mtc)}"),
            ],
        ),
        # COLD SHUTDOWN BRANCHES 
        Branch(
            name="rodIn_cold",
            comment=f"Cold Rodded State ({settings.t_cold_SD:.0f} K with no xenon)",
            directives=[
                BranchDirective(f"repm water_GT {settings.absorber_name}"),
                *[BranchDirective(f"repm {m} {m_cold}") for m, m_cold in fuel_pairs],
                *[
                    BranchDirective(
                        f"stp {m} {fuel_density} {settings.t_cold_SD:.1f}"
                    )
                    for m, _ in fuel_pairs  
                ],
                BranchDirective(
                    f"stp water {settings.rho_cold_cool:.5f} {settings.t_cold_SD:.1f}"
                    f" lwtr {c_low} {c_high}"
                ),
                BranchDirective(f"xenon 0"),
                BranchDirective(f"var TFU {int(settings.t_cold_SD)}"),
                BranchDirective(f"var TCO {int(settings.t_cold_SD)}"),
            ],
        ),
        ]
    pts = burnup_points if (burnup_enabled) else [0.0]
    coefcard = CoefCard(burnup_points=pts, branch_order=[b.name for b in branches])

    return branches, coefcard
from .serpent_objects import Detector, BurnupSettings, RunSettings

def build_case(
    geometry_name: str,            
    absorber_name: str,
    fuel_enrichment: float,
    gad_enrichment: float,
    gd_conc: float,
    detectors: list[Detector],
    burnup_settings:BurnupSettings,
    run_settings:RunSettings,
    branching_settings:Optional[BranchingSettings] = None,
    iteration: Optional[int] = 0,
    geometry: Optional[Geometry] = None,
    fuel_radii: Optional[list] = None

) -> RunCase:
    """Collates all the settings for this specific run and combines them into one RunCase object for easy rendering

    Args:
        geometry_name (str):  now that geom_opti is capable of running (incl with a fixed geom) a geometry object which hasa name is always passed (and fuel raddi shouldnt need to(needs implementing cuz of Ur)) so this is technically depreciated
        fuel_enrichment (float): f_enr
        gad_enrichment (float): g_enr
        gd_conc (float): gad_conc
        detectors (list[Detector]): list of detectors
        burnup_settings (BurnupSettings): burnup settings object
        run_settings (RunSettings): run settings object
        branching_settings (Optional[BranchingSettings], optional): branchin settings object. Defaults to None.
        iteration (Optional[int], optional): trial number. Defaults to 0.
        geometry (Optional[Geometry], optional): geometry object for current trial. Defaults to None.
        fuel_radii (Optional[list], optional): fuel radii for current trial. Defaults to None.

    Raises:
        ValueError: branching_settings must be provided when burnup_settings.branching is True

    Returns:
        RunCase: RunCase object now conatain all neccessary info to create serpent files
    """



    # 1. Resolve fuel materials and determine if Gd is active

    tfuel = run_settings.tfuel

    if burnup_settings.branching ==True:
         if branching_settings is None:
                    raise ValueError("branching_settings must be provided when burnup_settings.branching is True.") 
         tfuel_cold = int(branching_settings.t_cold_SD  )
    else:
        tfuel_cold = 500

    fuels, has_gad = resolve_fuels(
        fuel_enrichment=fuel_enrichment,
        gad_enrichment=gad_enrichment,
        gd_conc=gd_conc,
        t_fuel_hot=tfuel,
        t_fuel_cold=tfuel_cold,
    )

    assert geometry is not None
    layers = geometry.pins[0].layers
    fuel_radii = [layers[0][1], layers[1][1], layers[2][1]]

    Ur = f"_Ur_{fuel_radii[0]:.3f}_" if fuel_radii is not None else "_"

    # 2. Build geometry only if it was not provided
    if geometry is None:
        rows = pwr17_layout1()
        if fuel_radii is not None:
            geometry = _build_geometry17x17(
                name=geometry_name, 
                rows=rows, 
                has_gad=has_gad, 
                fuel_radii=fuel_radii
            )
        else:
            geometry = _build_geometry17x17(
                name=geometry_name, 
                rows=rows, 
                has_gad=has_gad
            )

         
    # Moved outside try-except block so absorber_mat is always instantiated
    absorber_mat = ABSORBER_VARIANTS[absorber_name]()

    case_name = f"{iteration}_fU{fuel_enrichment:.3f}_gU{gad_enrichment:.3f}_gd{gd_conc:.3f}{Ur}{geometry_name}_{absorber_name}"

    ### this branch logic needs revising not sure what we need yet
    if burnup_settings.branching == True:
        # 3. Build branches (adjusts coef card and repm directives based on burnup/Gd state)

        assert branching_settings is not None
        branches, coef = build_branches(
            settings=branching_settings, # type: ignore
            burnup_enabled=burnup_settings.enabled,

        )
        return RunCase(
            case_name=case_name,
            header_comment=f"{case_name}",
            materials=fuels + common_materials() + [absorber_mat],
            therm=common_therm(),
            geometry=geometry, # type: ignore
            detectors=detectors,
            burnup=burnup_settings,
            branching_settings=branching_settings,
            run_settings=run_settings,
            branches=branches,
            coef=coef,
        )

    else:
        return RunCase(
            case_name=case_name,
            header_comment=f"case={case_name}",
            materials=fuels + common_materials() + [absorber_mat],
            therm=common_therm(),
            geometry=geometry, # type: ignore
            detectors=detectors,
            burnup=burnup_settings,
            run_settings=run_settings,
        )
