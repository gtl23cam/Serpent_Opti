"""serpent_runner.py
    
Structured representation of the pieces that go into a Serpent input
file + its accompanying branches.inc, so they can be generated
programmatically instead of hand-edited.

Design principle: each dataclass mirrors one syntactic block of a
Serpent input. 

Renders RunCase dataclasses into main .inp files and _branches.inc files.
Forces ASCII encoding for output files.
"""

from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Nuclide:
    zaid: str  # e.g. "92235.09c"
    frac: (
        float  # mass or atom fraction (sign convention is the caller's responsibility)
    )
    comment: Optional[str] = None


@dataclass
class Material:
    name: str
    density: float  # signed: negative = mass density (g/cc), positive = atom density
    nuclides: list[Nuclide]
    tmp: Optional[float] = None
    moder: Optional[str] = None  # e.g. "lwtr 1001"
    burn: Optional[int] = None  # depletion zone flag
    rgb: Optional[str] = None  # e.g. "255 255 150"
    header_comment: Optional[str] = None


@dataclass
class ThermScatt:
    name: str  # e.g. "lwtr"
    temp: float
    libs: list[str]  # e.g. ["lwj3.11t", "lwj3.13t"]


@dataclass
class FuelSpecification:
    """
    Specification for one fuel material.
    """

    # Material name used in Serpent
    name: str

    # Fuel properties
    enrichment: float  # wt-% U-235
    gad_loading: float  # wt-% Gd2O3

    # Material properties
    density: float = -10.3070
    burn: int = 1
    rgb: str = "255 255 150"

    # Temperature information
    temperature: float = 900.0
    xs: str = "09c"

    # Optional description
    comment: str = ""


@dataclass
class Pin:
    name: str
    # list of (material_name, outer_radius); last entry has radius=None
    # (fills out to infinity / next pin ring)
    layers: list[tuple[str, Optional[float]]]
    comment: Optional[str] = None


@dataclass
class Lattice:
    name: str
    lat_type: int
    x0: float
    y0: float
    nx: int
    ny: int
    pitch: float
    rows: list[list[str]]  # nx entries per row, ny rows — pin names


@dataclass
class Geometry:
    """One complete geometry variant: pins + lattice + outer boundary."""

    name: str
    pins: list[Pin]
    lattice: Lattice
    usym: Optional[str] = None  # raw "set usym ..." line, if used
    outer_surface: str = "surf s1 sqc  0.0 0.0 10.752"
    cells: list[str] = field(
        default_factory=lambda: [
            "cell c1 0 fill lat1     -s1",
            "cell c2 0 outside        s1",
        ]
    )


@dataclass
class Detector:
    raw: (
        str  # kept as a raw line — detector syntax varies too much to model generically
    )


@dataclass
class BurnupSettings:
    enabled: bool
    branching: bool
    points: list[float]  # dep butot points, MWd/kgU
    div_lines: list[str]  # raw "div ..." lines
    mcvol: int = 10_000_000
    inventory: str = "all"
    pcc: str = "leli 10 10"
    declib: str = ""
    nfylib: str = ""
    egrid: str = "5e-5 1e-9 15.0"


@dataclass
class RunSettings:
    tfuel: float
    power: float
    bc: int = 2
    pop: str = "10000 100 20"
    plot: str = "3 700 700"
    mesh: str = "3 700 700"
    extra_settings: list[str] = field(
        default_factory=list
    )  # e.g. ["set gcu -1", "set repro 1"]


@dataclass
class BranchDirective:
    """One line inside a branch block, e.g. 'repm water_GT B4C' or
    'var TFU 500' or 'stp water -0.76105 500 lwtr lwj3.07t lwj3.11t'."""

    raw: str


@dataclass
class Branch:
    name: str
    directives: list[BranchDirective] = field(default_factory=list)
    comment: Optional[str] = None


@dataclass
class CoefCard:
    burnup_points: list[float]
    branch_order: list[str]  # must match Branch.name values, in output order


@dataclass
class RunCase:
    """Everything needed to render one (main_input, branches.inc) pair."""

    case_name: str
    materials: list[Material]
    therm: list[ThermScatt]
    geometry: Geometry
    detectors: list[Detector]
    burnup: BurnupSettings
    run_settings: RunSettings
    branching_settings: Optional[BranchingSettings] = None

    branches: list[Branch] | None = None
    coef: CoefCard | None = None

    header_comment: str = ""


@dataclass
class BranchingSettings:
    absorber_name: str = "B4C"
    has_gad: bool = True
    coef_points: list[float] = field(default_factory=list)
    # System Temperatures (K)
    t_hfp_fuel: float = 950.0
    t_hot_cool: float = 580.0  # Hot coolant & HZP base fuel temp
    t_cold_SD: float = 300.0  # Cold shutdown temp

    # Densities (g/cm^3)
    rho_hot_cool: float = -0.70000
    rho_cold_cool: float = -0.83100
    rho_hot_mtc: float = -0.68000  # Perturbed @ 600 K (+20 K)

    # Perturbation Deltas
    dt_ftc: float = 30.0
    dt_mtc: float = 20.0

    # S(a,b) Brackets from xsdata file
    sab_hot_pair: tuple[str, str] = ("lwj3.11t", "lwj3.13t")  # 574K - 624K
    sab_cold_pair: tuple[str, str] = ("lwj3.00t", "lwj3.01t")  # 294K - 324K
