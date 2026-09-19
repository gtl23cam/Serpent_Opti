# main.py
import os
THREADS_PER_WORKER = "7"
os.environ["OMP_NUM_THREADS"] = THREADS_PER_WORKER
os.environ["MKL_NUM_THREADS"] = THREADS_PER_WORKER
os.environ["OPENBLAS_NUM_THREADS"] = THREADS_PER_WORKER
os.environ["NUMEXPR_NUM_THREADS"] = THREADS_PER_WORKER
import multiprocessing as mp
from pathlib import Path
from functools import partial
import optuna
from optuna.samplers import TPESampler
from optuna.trial import TrialState
# Custom project modules
from constraints import constraints
from evaluate_trial import create_and_evaluate
from utils import get_trial_failures

N_WORKERS = 5  # parallel Optuna trials
THREADS_PER_WORKER = 7  # OpenMP threads per Serpent instance - needs to match in opti utils to calculate what specific core to run on
name = "geom_opti_TH_12"
notes = "Exactly same settings as opti_TH_4, just with the new code base and to check change in convergence"
Path(name).mkdir
OUTPUT_DIR = Path("Opti_runs") /Path(name)

if __name__ == "__main__":

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    manager = mp.Manager()
    shared_cache = manager.dict()
    total_eval_requests = mp.Value("i", 0)
    sss2_run_count = mp.Value("i", 0)

    bound_objective = partial(
        create_and_evaluate,
        shared_cache=shared_cache,
        total_eval_requests=total_eval_requests,
        sss2_run_count=sss2_run_count,
        output_dir = OUTPUT_DIR, 
    )
    bound_constraints = partial(constraints, output_dir=OUTPUT_DIR)

    sampler = TPESampler(
        multivariate=True,
        group=True,
        n_startup_trials=20,
        n_ei_candidates=100,
        constant_liar=True,
        constraints_func=bound_constraints
    )

    study = optuna.create_study(
        study_name=name,
        storage="optuna_database/sqlite:///serpent_optuna.db",
        direction="minimize",
        sampler=sampler,
    )
    study.set_user_attr("notes",notes)

## for adding more trials to a study after completion, uncomment the following lines and comment out the above study creation line.

    # study = optuna.load_study(
    #     study_name=name,
    #     storage="sqlite:///serpent_optuna.db",
    #     sampler=sampler,
    # )

    study.enqueue_trial(
    {
        "fuel_enrichment": 3.5,
        "gad_enrichment": 0.7,
        "gd_conc": 9.0,
        "fuel_radius" : 0.48,
        "n_gd_axis": 2,
        "n_gt_axis": 4,
        "n_gd_interior": 1,
        "n_gt_interior": 1,
        "gd_axis_w_0": 0.23333333333333334,
        "gd_axis_w_1": 0.7,
        "gd_axis_w_2": 0.7,
        "gd_axis_w_3": 0.7,
        "gt_axis_w_0": 0.3181818181818182,
        "gt_axis_w_1": 0.3181818181818182,
        "gt_axis_w_2": 0.5909090909090909,
        "gt_axis_w_3": 0.5909090909090909,
        "gd_interior_w_0": 0.5892857142857143,
        "gd_interior_w_1": 0.5892857142857143,
        "gd_interior_w_2": 0.5892857142857143,
        "gd_interior_w_3": 0.5892857142857143,
        "gt_interior_w_0": 0.46296296296296297,
        "gt_interior_w_1": 0.46296296296296297,
        "gt_interior_w_2": 0.46296296296296297,
        "gt_interior_w_3": 0.46296296296296297,
    }
)

    study.optimize(bound_objective, n_trials=250, n_jobs=N_WORKERS) # type: ignore

    completed = study.get_trials(states=[TrialState.COMPLETE])
    pruned = study.get_trials(states=[TrialState.PRUNED])
    failed = study.get_trials(states=[TrialState.FAIL])

    print(f"Completed: {len(completed)} | Pruned: {len(pruned)} | Failed: {len(failed)}")

    for t in study.trials:
        failures = get_trial_failures(t,constraints)
        if failures:
            print(f"Trial {t.number} failed due to: {failures}")

    # Output Post-run Statistics
    df = study.trials_dataframe()
    print(df["state"].value_counts())
    try:
        best_trial = study.best_trial
        print(f"Best Trial Number: {best_trial.number}")
        print(f"Best Value: {best_trial.value}")
        print(f"Best Params: {best_trial.params}")
        print("Parameters:")
        for k, v in study.best_trial.params.items():
                print(f"  {k}: {v}")
    except ValueError:
        print("No feasible trials were completed in this study.")

