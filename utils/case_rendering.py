from pathlib import Path

def _render_material(mat) -> str:
    lines = []
    if mat.header_comment:
        lines.append(f"% --- {mat.header_comment}")

    header = f"mat {mat.name} {mat.density}"
    if mat.tmp:
        header += f" tmp {mat.tmp}"
    if mat.moder:
        header += f" moder {mat.moder}"
    if mat.rgb:
        header += f" rgb {mat.rgb}"
    if mat.burn:
        header += f" burn {mat.burn}"
    lines.append(header)

    for nuc in mat.nuclides:
        line = f"{nuc.zaid:<14s} {nuc.frac:14.6e}"
        if nuc.comment:
            line += f"   % {nuc.comment}"
        lines.append(line)

    return "\n".join(lines)


def _render_pin(pin) -> str:
    lines = []
    if pin.comment:
        lines.append(f"% --- {pin.comment}")
    lines.append(f"pin {pin.name}")
    for mat_name, radius in pin.layers:
        line = f"{mat_name:<11s}"
        if radius is not None:
            line += f"{radius}"
        lines.append(line)
    return "\n".join(lines)


def render_main_input(case) -> str:
    parts = []

    parts.append(f"% --- {case.header_comment or case.case_name}\n")
    if case.branches:
        parts.append("% --- Include branch definitions from a file\n")
        parts.append(f'include "./{case.case_name}_branches.inc"\n\n')

    parts.append(
        "/************************\n"
        " * Material definitions *\n"
        " ************************/\n"
    )
    for mat in case.materials:
        parts.append(_render_material(mat) + "\n")

    for th in case.therm:
        parts.append(f"therm {th.name} {th.temp} {' '.join(th.libs)}")
    parts.append("")

    parts.append(
        "/************************\n"
        " * Geometry definitions *\n"
        " ************************/\n"
    )
    for pin in case.geometry.pins:
        parts.append(_render_pin(pin) + "\n")

    lat = case.geometry.lattice
    parts.append(
        f"lat {lat.name} {lat.lat_type} {lat.x0} {lat.y0} {lat.nx} {lat.ny} {lat.pitch}"
    )
    for row in lat.rows:
        parts.append(" ".join(row))
    parts.append("")

    if case.geometry.usym:
        parts.append(case.geometry.usym)
    parts.append(case.geometry.outer_surface)
    parts.append("")
    for cell in case.geometry.cells:
        parts.append(cell)
    parts.append("")

    parts.append(
        "/******************\n" " * Run parameters *\n" " ******************/\n"
    )
    rs = case.run_settings
    parts.append(f"set power {rs.power}")
    parts.append(f"set bc {rs.bc}")
    parts.append(f"set pop {rs.pop}")
    parts.append(f"plot {rs.plot}")
    parts.append(f"mesh {rs.mesh}")
    if rs.extra_settings:
        parts.extend(rs.extra_settings)
    parts.append("")

    for det in case.detectors:
        parts.append(det.raw)
    parts.append("")

    parts.append(
        "/***************************************\n"
        " * Settings for the burnup calculation *\n"
        " ***************************************/\n"
    )
    bu = case.burnup
    if bu.enabled:
        parts.append(f"dep butot {'  '.join(str(p) for p in bu.points)}\n")
        for line in bu.div_lines:
            parts.append(line)
        parts.append("")
        parts.append(f"set mcvol {bu.mcvol}")
        parts.append(f"set inventory {bu.inventory}")
        parts.append(f"set pcc {bu.pcc}")
        parts.append(f'set declib "{bu.declib}"')
        parts.append(f'set nfylib "{bu.nfylib}"')
        parts.append(f"set egrid {bu.egrid}")

    return "\n".join(parts) + "\n"


def render_branches(case) -> str:
    parts = []

    if case.header_comment:
        parts.append(f"% {case.header_comment}")

    for br in case.branches:
        parts.append(f"branch {br.name}")
        for d in br.directives:
            parts.append(d.raw)
        parts.append("")

    coef = case.coef
    parts.append(
        f"coef   {len(coef.burnup_points)}   "
        f"{' '.join(str(p) for p in coef.burnup_points)}"
    )
    parts.append(f"{len(coef.branch_order)}   {' '.join(coef.branch_order)}")

    return "\n".join(parts)


def render_case_text(case):
    return render_main_input(case), render_branches(case)


def render_case(case, output_dir: Path):
    """Render one RunCase to disk using strict ASCII encoding."""
    case_dir = output_dir / case.case_name
    case_dir.mkdir(parents=True, exist_ok=True)

    main_text, branches_text = render_case_text(case)

    # Enforce ASCII output encoding
    (case_dir / f"{case.case_name}").write_text(main_text, encoding="ascii")
    (case_dir / f"{case.case_name}_branches.inc").write_text(
        branches_text, encoding="ascii"
    )

    return case_dir


def parse_branches_inc(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()

    # Strip Serpent '%' comments and blank lines
    clean_lines = []
    for line in lines:
        line = line.split("%", 1)[0].strip()
        if line:
            clean_lines.append(line)

    # Find the coef card
    coef_idx = None
    for idx, line in enumerate(clean_lines):
        if line.split()[0].lower() == "coef":
            coef_idx = idx
            break

    if coef_idx is None:
        raise ValueError(f"No 'coef' card found in {filepath}")

    coef_tokens = clean_lines[coef_idx].split()
    # coef_tokens: ['coef', N_burnup, bp1, bp2, ..., bpN]
    n_burnup = int(coef_tokens[1])
    burnup_points = [float(x) for x in coef_tokens[2 : 2 + n_burnup]]

    if len(burnup_points) != n_burnup:
        raise ValueError(
            f"coef card declares {n_burnup} burnup points but "
            f"{len(burnup_points)} were found: {burnup_points}"
        )

    # The line immediately after the coef card: N_branches name1 name2 ...
    if coef_idx + 1 >= len(clean_lines):
        raise ValueError(
            f"Expected a branch-list line after the coef card in {filepath}, "
            f"found end of file."
        )

    branch_tokens = clean_lines[coef_idx + 1].split()
    n_branches = int(branch_tokens[0])
    branch_order = branch_tokens[1 : 1 + n_branches]

    if len(branch_order) != n_branches:
        raise ValueError(
            f"Branch line declares {n_branches} branches but "
            f"{len(branch_order)} names were found: {branch_order}"
        )

    return {
        "branch_order": branch_order,
        "burnup_points": burnup_points,
        "n_branches": n_branches,
        "n_burnup": n_burnup,
        "restart_points_per_branch": {b: n_burnup for b in branch_order},
    }