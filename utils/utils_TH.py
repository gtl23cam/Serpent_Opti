import optuna
from scipy.integrate import quad
import numpy as np

# ==========================================
# 1. GLOBAL SYSTEM PARAMETERS
# ==========================================
P_e = 470e6  # Net Electrical Power [W]
pump_margin = 1.05  # 5% pumping power allowance
eta = 0.34  # Thermal efficiency
P_th = (P_e * pump_margin) / eta  # Total Thermal Power [W]

T_in = 290.0  # Coolant inlet temperature celsius
T_out_target = 340.0  # Target coolant outlet temperature well below 345


# N_sa = 121
RH_opt = 0.54

# ==========================================
# 3. THERMAL PROPERTIES & LIMITS
# ==========================================
k_f = 2.0  # UO2 fuel conductivity [W/m-K]
k_c = 15.0  # Zircaloy clad conductivity [W/m-K]
h_g = 5000.0  # Gap conductance [W/m^2-K]
cp_w = 5800.0  # Water heat capacity [J/kg-K]
mu_w = 9.0e-5  # Water dynamic viscosity [Pa-s]
k_w = 0.55  # Water thermal conductivity [W/m-K]
rho_w = 725.0  # Water density [kg/m^3]
delta_L = 0.1  # extrapolation offset


# Water / System Thermodynamic Properties (Assumed operating at ~15.5 MPa)
p_MPa = 15.5  # Primary pressure [MPa]
h_in = 1300.0  # Inlet enthalpy [kJ/kg]
h_f = 1607.0  # Saturation liquid enthalpy [kJ/kg]
h_fg = 998.0  # Latent heat of vaporization [kJ/kg]


def thermal_hydraulic_estimate(trial,f_rad=1.4, min_DNBR_target=1.3, max_T_centerline_target=2400.0, finished = False):
    start = 60
    stop = 220
    n_sa_range = range(start, stop, 1)
    valid_N_sa = None
    for N_sa in n_sa_range:
        min_dnbr, T_centerline_max, linear_assem_power, r_core, h_core = check_DNBR_and_centerline_temp(
            trial, f_rad, N_sa
        )
        if min_dnbr > min_DNBR_target and T_centerline_max < max_T_centerline_target:
            valid_N_sa = N_sa
            return min_dnbr, T_centerline_max, linear_assem_power, valid_N_sa, r_core, h_core
    if finished:
        print(f"Trial {trial.number} finished with DNBR={min_dnbr}, T_centerline_max={T_centerline_max}, f rad of {f_rad} and no valid N_sa found in range{start},{stop}.")
        return min_dnbr, T_centerline_max, linear_assem_power, N_sa, r_core, h_core
    else:
        print(f"PRUNED Trial {trial.number} BOL with DNBR={min_dnbr} and T_centerline_max={T_centerline_max} and no valid N_sa found in range{start},{stop}.")
        raise optuna.TrialPruned()
        
    

def check_DNBR_and_centerline_temp(
trial,F_rad, N_sa
    ):

    ##Assembly flow channel geometry and mass flow calculations
    fuel_pins_per_sa = trial.user_attrs.get("total_pins") - ((trial.user_attrs.get("total_guide_tubes") + trial.user_attrs.get("total_gad_pins")))
    pitch = trial.user_attrs.get("pitch")
    d_ci = (trial.user_attrs.get("fuel_radii")[1] * 2)/100
    d_co = (trial.user_attrs.get("fuel_radii")[2] * 2)/100
    W_sa = pitch * np.sqrt(trial.user_attrs.get("total_pins")) + 1.5e-3  # Inter-assembly gap [m]
    m_dot_core = P_th / (cp_w * (T_out_target - T_in))     # Total coolant mass flow rate required across the core [kg/s]
    A_flow = (pitch**2) - (np.pi * (d_co**2) / 4.0)  # Coolant flow area per pin cell [m^2]
    D_H = (4.0 * A_flow) / (np.pi * d_co)  # Hydraulic diameter [m]

    ## Core geometry and mass flow calculations
    A_core = N_sa * (W_sa**2)
    R_core = np.sqrt(A_core / np.pi)
    H_opt = R_core / RH_opt  # Active fuel height [m]
    # print(H_opt,R_core)
    L_e = H_opt + delta_L
    N_pins = N_sa * fuel_pins_per_sa
    L_total = N_pins * H_opt
    m_dot_pin = m_dot_core / (N_pins)  # Mass flow per pin [kg/s]
    G_kg = m_dot_pin / A_flow  # Mass flux [kg/m^2 s]
    G_kg_hot = G_kg * 0.95  # Mass flux of hot chanel slightly lower 

    # Linear and Surface Heat Ratings
    # NOTE: Assumes radially uniform volumetric heat generation (q''' = constant).
    # To increase fidelity, q'''(r) can be made variable by integrating in-core detector
    # outputs (e.g., SPNDs/fission chambers) to model thermal neutron self-shielding / rim effect.
    # This requires d_pellet and depresses peak T_centerline.
    q_prime_avg = P_th / L_total
    q_prime_hot_avg = q_prime_avg * F_rad
    q0 = (q_prime_hot_avg * H_opt) / (
        2 * (L_e / np.pi) * np.sin(np.pi * H_opt / (2 * L_e))
    )  # Peak linear power [W/m]


    linear_assem_power = P_th / (100 * N_sa * H_opt)     # Linear power per subassembly [W/cm]

    # Outer Surface Heat Flux Profile [kW/m^2] 
    q_double_prime = lambda z: (q0 / (np.pi * d_co * 1000.0)) * np.cos(
        np.pi * (z - H_opt / 2) / L_e
    )

    # 1. Heat Transfer Coefficient & Max Centerline Temp Calculations
    V_w = m_dot_pin / (A_flow * rho_w)
    Re = (rho_w * V_w * D_H) / mu_w
    Pr = (mu_w * cp_w) / k_w
    Nu = 0.023 * (Re**0.8) * (Pr**0.4)
    h_f_coef = (Nu * k_w) / D_H

    dT_coolant = q0 / (np.pi * d_co * h_f_coef)
    dT_clad = (q0 / (2 * np.pi * k_c)) * np.log(d_co / d_ci)
    dT_gap = q0 / (np.pi * d_ci * h_g)

    # Neither d_pellet nor q''' is needed for dT_fuel: substituting q0 = q''' * (pi * d_pellet^2 / 4) 
    # into the cylindrical conduction integral (dT = q''' * R^2 / 4k_f) cancels out d_pellet and q'''.
    dT_fuel = q0 / (4 * np.pi * k_f)

    T_bulk_peak = T_in + (0.5 * q_prime_hot_avg * H_opt) / (m_dot_pin * cp_w)
    T_centerline_max = T_bulk_peak + dT_coolant + dT_clad + dT_gap + dT_fuel

    # 2. W-3 DNBR AXIAL SWEEP
    z_mesh = np.linspace(0.4 * H_opt, H_opt, 30)
    dnbr_list = []
    q_cr_unif_list = []
    q_cr_nonunif_list =[]

    for z in z_mesh:
        # Integrated power up to height z to calculate enthalpy and quality
        power_integrated, _ = quad(
            lambda z_p: q_double_prime(z_p) * np.pi * d_co, 0, z
        )  # [kW]
        h_local = h_in + (power_integrated / m_dot_pin)  # [kJ/kg]
        xe_local = (h_local - h_f) / h_fg  # Steam quality [-]

        # Uniform CHF (W-3 SI Units)
        term1 = (2.022 - 0.06238 * p_MPa) + (0.1722 - 0.01427 * p_MPa) * np.exp(
            (18.177 - 0.5987 * p_MPa) * xe_local
        )
        term2 = (
            0.1484 - 1.596 * xe_local + 0.1729 * xe_local * abs(xe_local)
        ) * 2.326 * G_kg_hot + 3271.0
        term3 = 1.157 - 0.869 * xe_local
        term4 = 0.2664 + 0.8357 * np.exp(-124.1 * D_H)
        term5 = 0.8258 + 0.0003413 * (h_f - h_in)
        q_cr_unif = term1 * term2 * term3 * term4 * term5  # [kW/m^2]

        # F-Factor Correction
        C = (185.6 * (1 - xe_local) ** 4.31) / (G_kg_hot**0.478)
        # print(G_kg_hot, xe_local, C)
        integrand = lambda z_prime: q_double_prime(z_prime) * np.exp(-C * (z - z_prime))
        num_integral, _ = quad(integrand, 0, z)

        q_local = q_double_prime(z)
        F_factor = (C * num_integral) / (q_local * (1.0 - np.exp(-C * z)))

        # Local DNBR
        q_cr_nonunif = q_cr_unif / F_factor
        dnbr_local = q_cr_nonunif / q_local
        dnbr_list.append(dnbr_local)
        q_cr_nonunif_list.append(q_cr_nonunif)
        q_cr_unif_list.append(q_cr_unif)


        min_dnbr = min(dnbr_list)
        qcrnunif = q_cr_nonunif_list[dnbr_list.index(min(dnbr_list))]
        qcrunif = q_cr_unif_list[dnbr_list.index(min(dnbr_list))]


    return min_dnbr, T_centerline_max, linear_assem_power, R_core,H_opt