"""
material_funcs.py

Runtime material utilities: library loading, dynamic key resolution,
and standard common material collections.
"""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from .serpent_objects import Material, Nuclide, ThermScatt


def load_material_library(filename: str) -> dict:
    lines = Path(filename).read_text(encoding="ascii").splitlines()
    library = {}
    current = None
    nuclides = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("%"):
            continue

        if line.startswith("mat "):
            if current is not None:
                current.nuclides = nuclides
                library[current.name] = current

            header = line.split()
            name = header[1]
            density = float(header[2])
            tmp = float(header[header.index("tmp")+1]) if "tmp" in header else None
            rgb = " ".join(header[header.index("rgb")+1:header.index("rgb")+4]) if "rgb" in header else ""
            burn = int(header[header.index("burn")+1]) if "burn" in header else 0

            current = Material(name=name, density=density, tmp=tmp, rgb=rgb, burn=burn, nuclides=[])
            nuclides = []
        else:
            parts = line.split()
            if current and len(parts) >= 2:
                try:
                    nuclides.append(Nuclide(zaid=parts[0], frac=float(parts[1])))
                except ValueError:
                    pass

    if current is not None:
        current.nuclides = nuclides
        library[current.name] = current

    return library


def select_materials(material_file: str, names: list = None) -> list: # type: ignore
    library = load_material_library(material_file)
    if names is None:
        return list(library.values())

    selected = []
    for name in names:
        if name not in library:
            raise KeyError(f"Material '{name}' not found in {material_file}")
        selected.append(library[name])
    return selected

def resolve_fuels(
    fuel_enrichment: float,
    gad_enrichment: float,
    gd_conc: float,
    t_fuel_hot: float = 900,
    t_fuel_cold: float = 500,
    library_path: str = "../Serpent_Opti/mat_management/materials_library4.txt"
) -> tuple[list, bool]:
    """
    Returns (materials_list, has_gad_flag).
    """
    lib_file = Path(library_path)
    if not lib_file.is_file():
        raise FileNotFoundError(f"[Material Resolver Error] Library file not found: '{lib_file.resolve()}'")

    has_gad_rods = gd_conc > 0.0

    # Format temperature strings for key matching
    hot_temp_str = f"{t_fuel_hot}K"
    cold_temp_str = f"{t_fuel_cold}K"

    no_gad_hot_key = f"fuelNoGad_0.000gd_{fuel_enrichment:.3f}wt_{hot_temp_str}"
    no_gad_cold_key = f"fuelNoGad_0.000gd_{fuel_enrichment:.3f}wt_{cold_temp_str}"
    fuel_keys = [no_gad_hot_key, no_gad_cold_key]

    if has_gad_rods:
        gad_hot_key = f"fuelYesGad_{gd_conc:.3f}gd_{gad_enrichment:.3f}wt_{hot_temp_str}"
        gad_cold_key = f"fuelYesGad_{gd_conc:.3f}gd_{gad_enrichment:.3f}wt_{cold_temp_str}"
        fuel_keys.extend([gad_hot_key, gad_cold_key])

    fuels_raw = select_materials(str(lib_file), fuel_keys)

    fuels = []
    for raw_mat in fuels_raw:
        mat = deepcopy(raw_mat)
        if "NoGad" in mat.name:
            is_hot = hot_temp_str in mat.name
            mat.name = "fuelNoGad" if is_hot else "fuelNoGad_cold"
            fuels.append(mat)
            
            # If Gd is not present, alias/duplicate fuelNoGad as fuelYesGad 
            # so Serpent pin GG can resolve the material definition.
            if not has_gad_rods:
                mat_alias = deepcopy(mat)
                mat_alias.name = "fuelYesGad" if is_hot else "fuelYesGad_cold"
                fuels.append(mat_alias)

        elif "YesGad" in mat.name:
            mat.name = "fuelYesGad" if hot_temp_str in mat.name else "fuelYesGad_cold"
            fuels.append(mat)

    return fuels, has_gad_rods

def common_materials() -> list[Material]:
    return [
        Material(
            name="Zircaloy4",
            density=-6.56,
            tmp=610,
            header_comment="Cladding material Zircaloy-4",
            nuclides=[
                # Oxygen
                Nuclide("8016.03c", -1.19276e-03),
                # Chromium
                Nuclide("24050.03c", -4.16117e-05),
                Nuclide("24052.03c", -8.34483e-04),
                Nuclide("24053.03c", -9.64457e-05),
                Nuclide("24054.03c", -2.44600e-05),
                # Iron
                Nuclide("26054.03c", -1.12572e-04),
                Nuclide("26056.03c", -1.83252e-03),
                Nuclide("26057.03c", -4.30778e-05),
                Nuclide("26058.03c", -5.83334e-06),
                # Zirconium
                Nuclide("40090.03c", -4.97862e-01),
                Nuclide("40091.03c", -1.09780e-01),
                Nuclide("40092.03c", -1.69646e-01),
                Nuclide("40094.03c", -1.75665e-01),
                Nuclide("40096.03c", -2.89038e-02),
                # Tin
                Nuclide("50112.03c", -1.27604e-04),
                Nuclide("50114.03c", -8.83732e-05),
                Nuclide("50115.03c", -4.59255e-05),
                Nuclide("50116.03c", -1.98105e-03),
                Nuclide("50117.03c", -1.05543e-03),
                Nuclide("50118.03c", -3.35688e-03),
                Nuclide("50119.03c", -1.20069e-03),
                Nuclide("50120.03c", -4.59220e-03),
                Nuclide("50122.03c", -6.63497e-04),
                Nuclide("50124.03c", -8.43355e-04),
            ],
        ),
        Material(
            name="water",
            density=-0.70602,
            tmp=583,
            moder="lwtr 1001",
            rgb="200 200 255",
            nuclides=[
                Nuclide("O-16.03c", 3.333e-01),
                Nuclide("H-1.03c", 6.667e-01),
            ],
        ),
        Material(
            name="water_GT",
            density=-0.70602,
            tmp=583,
            moder="lwtr 1001",
            rgb="200 200 255",
            nuclides=[
                Nuclide("O-16.03c", 3.333e-01),
                Nuclide("H-1.03c", 6.667e-01),
            ],
        ),
    ]

def common_therm() -> list[ThermScatt]:
    return [ThermScatt(name="lwtr", temp=583, libs=["lwj3.11t", "lwj3.13t"])]

def absorber_B4C() -> Material:
    return Material(
        name="B4C",
        density=-2.52,
        header_comment="Control rod absorber: solid B4C",
        nuclides=[
            Nuclide("5010.03c", 0.15920),
            Nuclide("5011.03c", 0.64080),
            Nuclide("6000.03c", 0.20000),
        ],
    )

def absorber_AgInCd() -> Material:
    return Material(
        name="AgInCd",
        density=-10.01,
        tmp=583,
        rgb="180 180 180",
        header_comment="Ag-In-Cd control rod absorber",
        nuclides=[
            Nuclide("Ag-107.03c", 4.440e-01),
            Nuclide("Ag-109.03c", 4.130e-01),
        ],
    )

ABSORBER_VARIANTS = {
    "B4C": absorber_B4C,
    "AgInCd": absorber_AgInCd,
}
