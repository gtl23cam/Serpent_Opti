"""
geometries.py

Assembly lattice layouts and pin definitions.
Supports dynamic toggling of Gd pin materials when gad_loading == 0.0.
"""
from __future__ import annotations

from .serpent_objects import Geometry, Lattice, Pin
from typing import Optional
MAX_PICKS = 8  # default cap on picks per symmetry class; override per-category as needed

def _base_pins(has_gad: bool = True, fuel_radii: list = []):
    return [
        Pin(
            name="FF",
            comment="Normal fuel rod (no gadolinia in fuel)",
            layers=[
                ("fuelNoGad", fuel_radii[0]),
                ("void", fuel_radii[1]),
                ("Zircaloy4", fuel_radii[2]),
                ("water", None),
            ],
        ),
        Pin(
            name="GG",
            comment="Gadolinium fuel rod (uses fuelNoGad if Gd is not present)",
            layers=[
                ("fuelYesGad" if has_gad else "fuelNoGad", 0.3),
                ("void", 0.306154),
                ("Zircaloy4", 0.347914),
                ("water", None),
            ],
        ),
        Pin(
            name="ii",
            comment="Empty instrumentation thimble",
            layers=[
                ("water", 0.500),
                ("Zircaloy4", 0.5400),
                ("water", None),
            ],
        ),
        Pin(
            name="cc",
            comment="Empty control rod channel",
            layers=[
                ("water_GT", 0.500),
                ("Zircaloy4", 0.5400),
                ("water", None),
            ],
        ),
        Pin(
            name="ww",
            comment="Empty lattice position (just water)",
            layers=[("water", None)],
        ),
    ]



def get_partitioned_fuel_coords():
    """Splits 39 valid fuel pin coordinates into axis (4x) and interior (8x) sets. excluding the standard guide tube positions"""
    guide_tubes_rel = {(0, 3), (3, 3), (0, 6), (3, 6), (5, 5)}

    axis_coords = []  # Multiplicity 4 (dx == 0 or dx == dy)
    interior_coords = []  # Multiplicity 8 (0 < dx < dy)

    for dy in range(9):
        for dx in range(dy + 1):
            if (dx, dy) == (0, 0) or (dx, dy) in guide_tubes_rel:
                continue

            if dx == 0 or dx == dy:
                axis_coords.append((dx, dy))
            else:
                interior_coords.append((dx, dy))

    return axis_coords, interior_coords

def get_partitioned_lattice_coords():
    """Splits 39 valid fuel pin coordinates into axis (4x) and interior (8x) sets."""

    axis_coords = []  # Multiplicity 4 (dx == 0 or dx == dy)
    interior_coords = []  # Multiplicity 8 (0 < dx < dy)

    for dy in range(1,9):
        for dx in range(dy + 1):

            if dx == 0 or dx == dy:
                axis_coords.append((dx, dy))
            else:
                interior_coords.append((dx, dy))

    return axis_coords, interior_coords


def build_rows_from_partitioned_fuel(
    axis_indices: list[int], interior_indices: list[int]
) -> list[list[str]]:
    """Builds full 17x17 lattice rows from separated axis and interior sampled indices keeping guide tubes fixed."""
    axis_coords, interior_coords = get_partitioned_fuel_coords()

    grid = [["ww"] * 17 for _ in range(17)]
    grid[8][8] = "ii"  # Center

    # Guide tubes
    guide_tubes_rel = {(0, 3), (3, 3), (0, 6), (3, 6), (5, 5)}
    for dx, dy in guide_tubes_rel:
        grid[8 - dy][8 + dx] = "cc"

    # Base fuel pins
    for dx, dy in axis_coords + interior_coords:
        grid[8 - dy][8 + dx] = "FF"

    # Overwrite Gd pins from Axis pool
    for idx in axis_indices:
        dx, dy = axis_coords[idx]
        grid[8 - dy][8 + dx] = "GG"

    # Overwrite Gd pins from Interior pool
    for idx in interior_indices:
        dx, dy = interior_coords[idx]
        grid[8 - dy][8 + dx] = "GG"

    return grid

def build_rows_from_partitioned_latice(
    gt_axis_idx: list[int], gt_interior_idx: list[int],
    gd_axis_idx: list[int], gd_interior_idx: list[int],
) -> list[list[str]]:
    """Builds a full 17x17 lattice from sampled guide-tube and Gd indices,
    both drawn from the same symmetry-partitioned lattice pool and guaranteed
    disjoint by carve_two_categories."""
    axis_coords, interior_coords = get_partitioned_lattice_coords()

    grid = [["ww"] * 17 for _ in range(17)]
    grid[8][8] = "ii"  # Center

    for dx, dy in axis_coords + interior_coords:
        grid[8 - dy][8 + dx] = "FF"

    for idx in gt_axis_idx:
        dx, dy = axis_coords[idx]
        grid[8 - dy][8 + dx] = "cc"
    for idx in gt_interior_idx:
        dx, dy = interior_coords[idx]
        grid[8 - dy][8 + dx] = "cc"

    for idx in gd_axis_idx:
        dx, dy = axis_coords[idx]
        grid[8 - dy][8 + dx] = "GG"
    for idx in gd_interior_idx:
        dx, dy = interior_coords[idx]
        grid[8 - dy][8 + dx] = "GG"

    return grid

def build_geometry17x17(name: str, rows: list, has_gad: bool = True, fuel_radii: list = [0.3,0.306154,0.347914]) -> Geometry:
    return Geometry(
        name=name,
        pins=_base_pins(has_gad=has_gad, fuel_radii=fuel_radii),
        lattice=Lattice(
            name="lat1",
            lat_type=1,
            x0=0.0,
            y0=0.0,
            nx=17,
            ny=17,
            pitch=1.265,
            rows=rows,
        ),
        usym="set usym lat1 3 2 0.0 0.0 270 45",
    )

def sample_static_subset(trial, pool_size, n, prefix, max_picks=MAX_PICKS):
    weights = [trial.suggest_float(f"{prefix}_w_{i}", 0, 1.0) for i in range(max_picks)]
    n = min(n, pool_size)
    if n == 0:
        return []

    sorted_w = sorted(weights[:n])

    # Pool shrunk by (n - 1) to leave room for the spacing every pick after
    # the first one needs, so the spread-out result still fits in pool_size. (the first offset is zero, hence n-1)
    compressed_size = pool_size - (n - 1)

    # Map each sorted weight to a raw slot in the shrunk pool, then spread
    # picks apart by adding their rank — guarantees strictly increasing,
    # collision-free positions in the real pool.
    return [int(w * compressed_size) + i for i, w in enumerate(sorted_w)]


def sample_static_subset_test(pool_size, n, prefix, max_picks=MAX_PICKS):

    # weights = [trial.suggest_float(f"{prefix}_w_{i}", 0, 1.0) for i in range(max_picks)]
    if prefix == "gd_axis":
        weights = [0.25,0.69,0.7,0.7]
    elif prefix == "gt_axis":
        weights = [0.31,0.35,0.56,0.6]
    elif prefix == "gd_interior":
        weights = [0.59,0.7,0.7,0.7]
    elif prefix == "gt_interior":
        weights = [0.47,0.5,0.5,0.5]

    n = min(n, pool_size)
    if n == 0:
        return []

    sorted_w = sorted(weights[:n])

    # Pool shrunk by (n - 1) to leave room for the spacing every pick after
    # the first one needs, so the spread-out result still fits in pool_size. (the first offset is zero, hence n-1)
    compressed_size = pool_size - (n - 1)

    # Map each sorted weight to a raw slot in the shrunk pool, then spread
    # picks apart by adding their rank — guarantees strictly increasing,
    # collision-free positions in the real pool.
    return [int(w * compressed_size) + i for i, w in enumerate(sorted_w)]

def carve_two_categories(
    trial, coords, first_n, first_prefix, second_n, second_prefix,
    first_max=MAX_PICKS, second_max=MAX_PICKS,
):
    """Carve two disjoint, ordered subsets out of the same coordinate pool.
    `first_prefix` gets first claim — use this for the more constrained
    category (guide tubes over Gd). Returns index lists into `coords`."""
    first_idx = sample_static_subset(trial, len(coords), first_n, first_prefix, first_max)
    remaining = [i for i in range(len(coords)) if i not in set(first_idx)]
    second_local = sample_static_subset(trial, len(remaining), second_n, second_prefix, second_max)
    second_idx = [remaining[i] for i in second_local]
    return first_idx, second_idx

def carve_two_categories_test(
    coords, first_n, first_prefix, second_n, second_prefix,
    first_max=MAX_PICKS, second_max=MAX_PICKS,
):
    """Carve two disjoint, ordered subsets out of the same coordinate pool.
    `first_prefix` gets first claim — use this for the more constrained
    category (guide tubes over Gd). Returns index lists into `coords`."""
    first_idx = sample_static_subset_test(len(coords), first_n, first_prefix, first_max)
    remaining = [i for i in range(len(coords)) if i not in set(first_idx)]
    second_local = sample_static_subset_test(len(remaining), second_n, second_prefix, second_max)
    second_idx = [remaining[i] for i in second_local]
    return first_idx, second_idx

def sample_guide_and_gd(
    trial, axis_coords, interior_coords, max_gt_picks=MAX_PICKS, max_gd_picks=MAX_PICKS
):
    """Sample guide-tube and Gd pin counts/positions for both symmetry classes,
    guaranteeing no cell is claimed by both categories."""
    n_gt_axis = trial.suggest_int("n_gt_axis", 0, max_gt_picks)
    n_gt_interior = trial.suggest_int("n_gt_interior", 0, max_gt_picks)
    n_gd_axis = trial.suggest_int("n_gd_axis", 0, max_gd_picks)
    n_gd_interior = trial.suggest_int("n_gd_interior", 0, max_gd_picks)

    gd_axis_idx, gt_axis_idx = carve_two_categories(
        trial, axis_coords, n_gd_axis, "gd_axis", n_gt_axis, "gt_axis",
        max_gt_picks, max_gd_picks,
    )
    gd_interior_idx, gt_interior_idx = carve_two_categories(
        trial, interior_coords, n_gd_interior, "gd_interior", n_gt_interior, "gt_interior",
        max_gt_picks, max_gd_picks,
    )
    return gt_axis_idx, gt_interior_idx, gd_axis_idx, gd_interior_idx

def sample_guide_and_gd_test(
    axis_coords, interior_coords, max_gt_picks=MAX_PICKS, max_gd_picks=MAX_PICKS
):
    """Sample guide-tube and Gd pin counts/positions for both symmetry classes,
    guaranteeing no cell is claimed by both categories."""
    n_gt_axis = 4
    n_gt_interior = 1
    n_gd_axis = 2
    n_gd_interior = 1

    gd_axis_idx, gt_axis_idx = carve_two_categories_test(
        axis_coords, n_gd_axis, "gd_axis", n_gt_axis, "gt_axis",
        max_gt_picks, max_gd_picks,
    )
    gd_interior_idx, gt_interior_idx = carve_two_categories_test(
        interior_coords, n_gd_interior, "gd_interior", n_gt_interior, "gt_interior",
        max_gt_picks, max_gd_picks,
    )
    return gt_axis_idx, gt_interior_idx, gd_axis_idx, gd_interior_idx

    