from __future__ import annotations
import sys
from pathlib import Path

# Add parent directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from optimisation.BA_opti_2.Final_code.serpent_objects import FuelSpecification, Nuclide, Material

# ============================================================
# Fuel material generator library
# ============================================================



# Atomic masses (g/mol)

ATOMIC_MASS = {
    "U235": 235.0439299,
    "U238": 238.0507882,
    "O16": 15.99491461957,
    "Gd152": 151.9197995,
    "Gd154": 153.9208741,
    "Gd155": 154.9226305,
    "Gd156": 155.9221312,
    "Gd157": 156.9239686,
    "Gd158": 157.9241123,
    "Gd160": 159.9270624,
}

# Natural gadolinium isotopic abundances
# Fractional abundances (sum = 1)

GD_ABUNDANCE = {
    "152": 0.0020,
    "154": 0.0218,
    "155": 0.1480,
    "156": 0.2047,
    "157": 0.1565,
    "158": 0.2484,
    "160": 0.2186,
}

# Average atomic mass of natural gadolinium

GD_AVERAGE_MASS = sum(GD_ABUNDANCE[k] * ATOMIC_MASS[f"Gd{k}"] for k in GD_ABUNDANCE)

# Molecular masses

MW_UO2 = ATOMIC_MASS["U238"] + 2 * ATOMIC_MASS["O16"]

MW_GD2O3 = 2 * GD_AVERAGE_MASS + 3 * ATOMIC_MASS["O16"]


def generate_fuel_isotopes(
    enrichment,
    gad_loading=0.0,
):
    """
    Convert U enrichment and Gd2O3 loading (wt-%)
    into Serpent isotope fractions.

    Returns:
        list of (serpent isotope, fraction)
    """

    # Assume 100 g of fuel

    total_mass = 100.0

    # Split UO2 and Gd2O3

    mass_gd2o3 = total_mass * gad_loading / 100.0
    mass_uo2 = total_mass - mass_gd2o3

    # Uranium calculation

    # Uranium enrichment is wt-% of uranium

    mass_u = (
        mass_uo2
        * (
            enrichment / 100 * ATOMIC_MASS["U235"]
            + (1 - enrichment / 100) * ATOMIC_MASS["U238"]
        )
        / (
            enrichment / 100 * ATOMIC_MASS["U235"]
            + (1 - enrichment / 100) * ATOMIC_MASS["U238"]
            + 2 * ATOMIC_MASS["O16"]
        )
    )

    mass_u235 = mass_u * enrichment / 100
    mass_u238 = mass_u - mass_u235

    n_u235 = mass_u235 / ATOMIC_MASS["U235"]
    n_u238 = mass_u238 / ATOMIC_MASS["U238"]

    # Oxygen from UO2

    n_o16 = 2 * (n_u235 + n_u238)

    atoms = {
        "92235": n_u235,
        "92238": n_u238,
        "8016": n_o16,
    }

    # Gadolinium calculation

    if gad_loading > 0:

        n_gd2o3 = mass_gd2o3 / MW_GD2O3

        # oxygen from Gd2O3

        atoms["8016"] += 3 * n_gd2o3

        # two Gd atoms per molecule

        for iso, abundance in GD_ABUNDANCE.items():

            atoms[f"64{iso}"] = 2 * n_gd2o3 * abundance

    # Normalise to atom fractions

    total_atoms = sum(atoms.values())

    serpent_atoms = []

    for isotope, amount in atoms.items():

        serpent_atoms.append((isotope, amount / total_atoms))

    return serpent_atoms



def build_fuel_material(spec: FuelSpecification):
    """
    Create a Serpent Material object from a FuelSpecification.
    """

    isotopes = generate_fuel_isotopes(
        enrichment=spec.enrichment,
        gad_loading=spec.gad_loading,
    )

    nuclides = []

    for isotope, fraction in isotopes:

        nuclides.append(Nuclide(f"{isotope}.{spec.xs}", fraction))

    return Material(
        name=spec.name,
        density=spec.density,
        tmp=spec.temperature,
        rgb=spec.rgb,
        burn=spec.burn,
        header_comment=spec.comment,
        nuclides=nuclides,
    )
