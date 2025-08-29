#!/usr/bin/env python3
import os
import json
from datetime import datetime

PLANS_DIR = "plans"

def input_float(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("  ↳ Invalid number, please try again.")

def input_int(prompt):
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("  ↳ Invalid integer, please try again.")

def frange(start, end, step):
    x = start
    while x <= end + 1e-9:
        yield round(x, 9)
        x += step

def choose_method():
    methods = ["LSV", "CV", "SWV", "CA", "MSA"]
    print("\n  Select a method:")
    for i, m in enumerate(methods):
        print(f"   [{i}] {m}")
    while True:
        choice = input("   > ").strip()
        if choice.isdigit() and int(choice) < len(methods):
            return methods[int(choice)]
        print("   ↳ Invalid choice, please try again.")

def get_params(method):
    params = {}
    if method == "LSV":
        params = {
            "begin_potential": input_float("    Begin (V): "),
            "end_potential":   input_float("    End (V): "),
            "step_potential":  input_float("    Step (V): "),
            "scanrate":        input_float("    Scan rate (V/s): ")
        }
    elif method == "CV":
        params = {
            "begin_potential":   input_float("    Begin (V): "),
            "vtx1_potential":    input_float("    Vertex1 (V): "),
            "vtx2_potential":    input_float("    Vertex2 (V): "),
            "step_potential":    input_float("    Step (V): "),
            "scanrate":          input_float("    Scan rate (V/s): "),
            "n_scans":           input_int("    Number of scans: ")
        }
    elif method == "SWV":
        params = {
            "begin_potential":   input_float("    Begin (V): "),
            "end_potential":     input_float("    End (V): "),
            "step_potential":    input_float("    Step (V): "),
            "amplitude":         input_float("    Amplitude (V): "),
            "frequency":         input_float("    Frequency (Hz): ")
        }
    elif method == "CA":
        params = {
            "e":             input_float("    Potential (V): "),
            "run_time":      input_float("    Run time (s): "),
            "interval_time": input_float("    Interval time (s): ")
        }
    elif method == "MSA":
        params = {
            "equilibration_time": input_float("    Equilibration time (s): "),
            "interval_time":      input_float("    Interval time (s): "),
            "n_cycles":           input_int("    Number of cycles: "),
            "levels": []
        }
        n_lv = input_int("    Number of levels: ")
        for i in range(n_lv):
            lvl = input_float(f"      Level {i+1} potential (V): ")
            dur = input_float(f"      Level {i+1} duration (s): ")
            params["levels"].append({"level": lvl, "duration": dur})
    return params

def build_step():
    method = choose_method()
    step = {"method": method}

    sweep = input("   Do a parameter sweep? (y/n): ").strip().lower() == 'y'
    if sweep:
        step["type"] = "sweep"
        step["base_params"] = get_params(method)
        if method == "MSA":
            idx = input_int("    Which level to sweep (1-indexed): ") - 1
            step["modify_levels"] = True
            step["level_index"] = idx
            sp = input("    Sweep potential? (y/n): ").strip().lower() == 'y'
            sd = input("    Sweep duration? (y/n): ").strip().lower() == 'y'
            step["sweep_potential"] = sp
            step["sweep_duration"] = sd
            if sp:
                start = input_float("      Pot start: ")
                end   = input_float("      Pot end:   ")
                step["sweep_values"] = list(frange(start, end, input_float("      Pot step:  ")))
            if sd:
                start = input_float("      Dur start: ")
                end   = input_float("      Dur end:   ")
                step["sweep_values"] = list(frange(start, end, input_float("      Dur step:  ")))
        else:
            step["type"] = "sweep"
            step["sweep_param"] = input("    Parameter to sweep (exact key name): ").strip()
            step["base_params"] = get_params(method)
            vals = input("    Enter comma-separated values: ")
            step["sweep_values"] = [float(v) for v in vals.split(",") if v.strip()]
    else:
        step["type"] = "single"
        step["params"] = get_params(method)

    step["repeats"] = input_int("   How many repeats: ")
    # no more per-step concentration tagging here:
    # (global concentration will be applied in run.py)

    return step

def print_plan(plan):
    print(f"\n=== Plan: {plan['name']} ===")
    for i, s in enumerate(plan["sequence"], 1):
        m = s["method"]
        t = s["type"]
        rpt = s.get("repeats", 1)
        print(f" {i}. {m} [{t}], repeats={rpt}")
        if not plan["sequence"]:
            print(" (no steps defined yet)")

def edit_plan(plan):
    while True:
        print_plan(plan)
        print("\nChoose an action:")
        print(" [A] Add step")
        if plan["sequence"]:
            print(" [E] Edit step")
            print(" [D] Delete step")
        print(" [F] Finish and save")
        choice = input(" > ").strip().upper()
        if choice == 'A':
            plan["sequence"].append(build_step())
        elif choice == 'E' and plan["sequence"]:
            idx = input_int("   Step number to edit: ") - 1
            if 0 <= idx < len(plan["sequence"]):
                print("   Re-building this step:")
                plan["sequence"][idx] = build_step()
            else:
                print("   ↳ Invalid step number.")
        elif choice == 'D' and plan["sequence"]:
            idx = input_int("   Step number to delete: ") - 1
            if 0 <= idx < len(plan["sequence"]):
                del plan["sequence"][idx]
                print("   ↳ Step removed.")
            else:
                print("   ↳ Invalid step number.")
        elif choice == 'F':
            return plan
        else:
            print("   ↳ Invalid choice, please try again.")

def main():
    os.makedirs(PLANS_DIR, exist_ok=True)
    while True:
        name = input("\nEnter plan name: ").strip()
        if not name:
            print(" ↳ Plan name cannot be empty.")
            continue

        plan_file = os.path.join(PLANS_DIR, f"{name}.json")
        if os.path.exists(plan_file):
            # existing: modify in place
            print(f"Plan '{name}' already exists.")
            opt = input(" [1] Modify existing [2] Start from scratch\n  > ").strip()
            if opt == '1':
                with open(plan_file) as f:
                    plan = json.load(f)
                print("Loaded existing plan for editing.")
            else:
                plan = {"name": name,
                        "created": datetime.now().isoformat(),
                        "sequence": []}
        else:
            # NEW plan: offer clone or scratch
            print(f"Plan '{name}' does not exist yet.")
            opt = input(" [1] Start from scratch [2] Clone an existing plan\n  > ").strip()
            if opt == '2':
                # list all existing plans
                files = [f for f in os.listdir(PLANS_DIR) if f.endswith('.json')]
                for i, f in enumerate(files):
                    print(f"   [{i}] {f}")
                idx = input_int("   Select plan to clone by number: ")
                src = os.path.join(PLANS_DIR, files[idx])
                with open(src) as f:
                    src_plan = json.load(f)
                # deep‑copy metadata and sequence, but set new name & timestamp
                plan = {
                    "name": name,
                    "created": datetime.now().isoformat(),
                    "sequence": src_plan.get("sequence", []).copy()
                }
                print(f"Cloned '{files[idx]}' into new plan '{name}'.")
            else:
                plan = {"name": name,
                        "created": datetime.now().isoformat(),
                        "sequence": []}

        # now enter the existing edit loop unchanged
        plan = edit_plan(plan)

        # save
        with open(plan_file, 'w') as f:
            json.dump(plan, f, indent=4)
        print(f"\n↳ Plan saved to {plan_file}")

        again = input("\nDefine another plan? (y/n): ").strip().lower()
        if again != 'y':
            print("Exiting Plan Builder.")
            break


if __name__ == "__main__":
    main()
