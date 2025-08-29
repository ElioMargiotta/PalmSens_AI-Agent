#!/usr/bin/env python3
"""
run.py: Execute PalmSens experiment plans on one or more channels.

Supports both “one‐experiment‐for‐all‐channels” and
“per‐channel” experiment naming/tagging.
"""

import os
import json
import glob
import csv
import asyncio
from datetime import datetime
from pspython import pspyinstruments, pspymethods
from pspython.pspyfiles import save_session_file, load_session_file
from colorama import init, Fore, Style

init(autoreset=True)

METHOD_FUNC_MAP = {
    "LSV": pspymethods.linear_sweep_voltammetry,
    "CV":  pspymethods.cyclic_voltammetry,
    "SWV": pspymethods.square_wave_voltammetry,
    "CA":  pspymethods.chronoamperometry,
    "MSA": pspymethods.multi_step_amperometry
}

PLANS_DIR    = "plans"
SESSIONS_DIR = "sessions"


def input_int(prompt):
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("  ↳ Invalid integer; please try again.")


def parse_int_list(s):
    return [int(x) for x in s.split(",") if x.strip().isdigit()]


async def discover_instruments(timeout_seconds=10):
    print("\n🔍 Discovering PalmSens instruments...")
    try:
        available = await asyncio.wait_for(
            pspyinstruments.discover_instruments_async(), 
            timeout=timeout_seconds
        )
        if not available:
            print("❌ No instruments found. Check USB connection or drivers.")
            return None
        print(f"✓ Found {len(available)} instrument channel(s).")
        return available
    except asyncio.TimeoutError:
        print(f"❌ Instrument discovery timed out after {timeout_seconds} seconds.")
        return None


def choose_session():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    existing = sorted(d for d in os.listdir(SESSIONS_DIR)
                      if os.path.isdir(os.path.join(SESSIONS_DIR, d)))
    if existing:
        print("\nExisting sessions:")
        for i, name in enumerate(existing):
            print(f" [{i}] {name}")
        print(f" [{len(existing)}] Create new session")
        choice = input("Select session index: ").strip()
        if choice.isdigit() and int(choice) < len(existing):
            return existing[int(choice)]
    new_name = ""
    while not new_name:
        new_name = input("Enter new session name: ").strip()
    return new_name


async def connect_channels(channels, available):
    managers = {}
    for ch in channels:
        print(f"[CH{ch}] Connecting...", end="", flush=True)
        mgr = pspyinstruments.InstrumentManagerAsync()
        await mgr.connect(available[ch])
        managers[ch] = mgr
        print(" ✓")
    return managers


async def run_one(mgr, ch, method_name, params, title,
                  conc, session_dir, all_meas, exp_desc):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base  = os.path.join(session_dir, exp_desc, method_name)
    files = os.path.join(base, "files"); os.makedirs(files, exist_ok=True)
    logs  = os.path.join(base, "logs");  os.makedirs(logs,  exist_ok=True)

    conc_tag = f"_c{conc}" if conc else ""
    safe     = title.replace(" ", "_")
    fname    = f"ch{ch}{conc_tag}_{timestamp}_{safe}"
    csvp     = os.path.join(files, fname + ".csv")
    jsonp    = os.path.join(logs,  fname + ".json")

    with open(csvp, "w", newline="") as cf:
        writer = csv.writer(cf)
        header = (["Time (s)", "Current (uA)"]
                  if method_name == "MSA"
                  else ["Potential (V)", "Current (uA)"])
        writer.writerow(header)
        mgr.new_data_callback = lambda data: [
            writer.writerow([pt["x"], pt["y"]]) for pt in data
        ]
        method_func = METHOD_FUNC_MAP[method_name]
        method_obj  = method_func(**params)
        meas        = await mgr.measure(method_obj,
                                        return_dotnet_object=True)
        all_meas.append(meas)
    print(f"[CH{ch}] Data → {csvp}")

    save_params = params
    if method_name == "MSA" and "_raw_levels" in params:
        save_params = params.copy()
        save_params["levels"] = save_params.pop("_raw_levels")

    log = {
        "channel":      ch,
        "method":       method_name,
        "title":        title,
        "timestamp":    timestamp,
        "parameters":   save_params,
        "concentration": conc
    }
    with open(jsonp, "w") as jf:
        json.dump(log, jf, indent=4)
    print(f"[CH{ch}] Log  → {jsonp}")


async def run_channel(ch, plan, session_dir, managers, all_meas, exp_desc):
    mgr = managers[ch]
    for idx_step, step in enumerate(plan["sequence"], start=1):
        m    = step["method"]
        typ  = step.get("type", "single")
        reps = step.get("repeats", 1)
        conc = step.get("concentration")

        if typ == "single":
            if m == "MSA":
                raw    = step["params"]["levels"]
                params = {k: v for k, v in step["params"].items()
                          if k != "levels"}
                params["_raw_levels"] = raw
                params["levels"] = [
                    pspymethods.multi_step_amperometry_level(**lvl)
                    for lvl in raw
                ]
            else:
                params = step["params"]

            for i in range(1, reps + 1):
                title = f"{m.lower()}_step{idx_step}_run{i}"
                await run_one(mgr, ch, m, params, title,
                              conc, session_dir, all_meas, exp_desc)

        elif typ == "sweep":
            base = step["base_params"]
            if m == "MSA" and step.get("modify_levels"):
                lvl_idx = step["level_index"]
                for val in step["sweep_values"]:
                    raw = [lvl.copy() for lvl in base["levels"]]
                    if step.get("sweep_potential"):
                        raw[lvl_idx]["level"] = val
                    if step.get("sweep_duration"):
                        raw[lvl_idx]["duration"] = val
                    params = {k: v for k, v in base.items()
                              if k != "levels"}
                    params["_raw_levels"] = raw
                    params["levels"] = [
                        pspymethods.multi_step_amperometry_level(**l)
                        for l in raw
                    ]
                    for i in range(1, reps + 1):
                        title = f"{m.lower()}_lvl{lvl_idx+1}_{val}_run{i}"
                        await run_one(mgr, ch, m, params, title,
                                      conc, session_dir, all_meas, exp_desc)
            else:
                sweep_param = step["sweep_param"]
                for val in step["sweep_values"]:
                    params = dict(base)
                    params[sweep_param] = val
                    for i in range(1, reps + 1):
                        title = f"{m.lower()}_{sweep_param}{val}_run{i}"
                        await run_one(mgr, ch, m, params, title,
                                      conc, session_dir, all_meas, exp_desc)
        else:
            print(f"[CH{ch}] ⚠ Unknown step type '{typ}'—skipping.")


async def main():
    # 1) Discover instruments
    available = await discover_instruments()
    if available is None:
        return

    # 2) Choose or create session
    session_name = choose_session()
    session_dir  = os.path.join(SESSIONS_DIR, session_name)
    os.makedirs(session_dir, exist_ok=True)
    session_file = os.path.join(session_dir,
                                f"{session_name}.pssession")

    # 3) Select channels
    print("\nAvailable channel indices:")
    for idx in range(len(available)):
        print(f" [{idx}] Channel {idx}")
    ch_input = input("Select channel(s) (comma separated): ").strip()
    channels = parse_int_list(ch_input)
    channels = [ch for ch in channels
                if 0 <= ch < len(available)]
    if not channels:
        print("❌ No valid channels selected. Exiting.")
        return

    # 4) Same‐or‐per‐channel experiment?
    same_exp = (input("\nSame experiment for all channels? (y/n): ")
                .strip().lower() == "y")

    assignments = []
    plan_paths  = sorted(glob.glob(os.path.join(PLANS_DIR, "*.json")))
    if not plan_paths:
        print("❌ No plans found in 'plans/'. Run plan_builder.py first.")
        return

    if same_exp:
        # one title/conc for all
        exp_desc    = input("\nEnter experiment title: ").strip()
        global_conc = (input("Enter concentration tag "
                             "(e.g. 1e-6), or blank: ")
                       .strip() or None)
        exp_dir = os.path.join(session_dir, exp_desc)
        os.makedirs(exp_dir, exist_ok=True)
        # save info
        info_path = os.path.join(exp_dir, "experiment_info.txt")
        with open(info_path, "w") as f:
            f.write(f"Session: {session_name}\n")
            f.write(f"Experiment: {exp_desc}\n")
            if global_conc:
                f.write(f"Concentration: {global_conc}\n")
        print(f"🗒️  Saved info: {info_path}\n")

        # assign plans
        for ch in channels:
            print(f"\nPlans for channel {ch}:")
            for i, p in enumerate(plan_paths):
                print(f" [{i}] {os.path.basename(p)}")
            idx = input_int(f"Select plan index for CH{ch}: ")
            plan_data = json.load(open(plan_paths[idx]))
            for step in plan_data["sequence"]:
                step["concentration"] = global_conc
            assignments.append({
                "ch": ch,
                "plan": plan_data,
                "exp_desc": exp_desc
            })

        # single combined summary
        summary_lines = [
            f"Experiment: {exp_desc}",
            f"Concentration: {global_conc or '—'}",
            f"Channels: {', '.join(map(str, channels))}",
            ""
        ]
        for a in assignments:
            ch   = a["ch"]
            plan = a["plan"]
            summary_lines.append(f"--- Channel {ch} Sequence ---")
            if plan.get("name"):
                summary_lines.append(f"Plan Name: {plan['name']}")
            for i, step in enumerate(plan["sequence"], start=1):
                m   = step["method"]
                rpt = step.get("repeats", 1)
                summary_lines.append(f"{i}. {m} (repeats: {rpt})")
                params = (step.get("params")
                          or step.get("base_params") or {})
                for k, v in params.items():
                    summary_lines.append(f"    • {k}: {v}")
            summary_lines.append("")

        plan_summary = os.path.join(exp_dir, "plan_summary.txt")
        with open(plan_summary, "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines))
        print(f"🗒️  Saved summary: {plan_summary}\n")

    else:
        # per‑channel title/conc
        for ch in channels:
            print(f"\n--- Channel {ch} Setup ---")
            exp_desc = input(f"Title for CH{ch}: ").strip()
            conc     = (input(f"Concentration for CH{ch} "
                              "(e.g. 1e-6), or blank: ")
                        .strip() or None)
            exp_dir = os.path.join(session_dir, exp_desc)
            os.makedirs(exp_dir, exist_ok=True)
            info_path = os.path.join(exp_dir,
                                     f"experiment_info_CH{ch}.txt")
            with open(info_path, "w") as f:
                f.write(f"Session: {session_name}\n")
                f.write(f"Experiment: {exp_desc}\n")
                if conc:
                    f.write(f"Concentration: {conc}\n")
            print(f"🗒️  Saved info: {info_path}")

            print(f"\nPlans for channel {ch}:")
            for i, p in enumerate(plan_paths):
                print(f" [{i}] {os.path.basename(p)}")
            idx        = input_int(f"Select plan index for CH{ch}: ")
            plan_data  = json.load(open(plan_paths[idx]))
            for step in plan_data["sequence"]:
                step["concentration"] = conc

            # write per‑channel summary
            summary_lines = [
                f"Experiment: {exp_desc}",
                f"Concentration: {conc or '—'}",
                f"Channel: {ch}",
                "",
                "--- Sequence ---"
            ]
            if plan_data.get("name"):
                summary_lines.insert(4,
                                     f"Plan Name: {plan_data['name']}")
            for i, step in enumerate(plan_data["sequence"], start=1):
                m   = step["method"]
                rpt = step.get("repeats", 1)
                summary_lines.append(f"{i}. {m} (repeats: {rpt})")
                params = (step.get("params")
                          or step.get("base_params") or {})
                for k, v in params.items():
                    summary_lines.append(f"    • {k}: {v}")
            summary_lines.append("")

            plan_summary = os.path.join(exp_dir,
                                        f"plan_summary_CH{ch}.txt")
            with open(plan_summary, "w", encoding="utf-8") as f:
                f.write("\n".join(summary_lines))
            print(f"🗒️  Saved summary: {plan_summary}\n")

            assignments.append({
                "ch": ch,
                "plan": plan_data,
                "exp_desc": exp_desc
            })

    # 5) Load or init existing session data
    if os.path.exists(session_file):
        print("Loading existing session…")
        existing = load_session_file(session_file,
                                     return_dotnet_object=True) or []
    else:
        existing = []
    all_measurements = existing

    # 6) Connect & run
    managers = await connect_channels(channels, available)
    tasks = []
    for a in assignments:
        tasks.append(
            run_channel(a["ch"], a["plan"],
                        session_dir, managers,
                        all_measurements, a["exp_desc"])
        )
    await asyncio.gather(*tasks)

    # 7) Disconnect & save
    await asyncio.gather(*(mgr.disconnect()
                           for mgr in managers.values()))
    save_session_file(session_file, all_measurements)
    print(f"\n✅ Session updated: {session_file}")


if __name__ == "__main__":
    asyncio.run(main())
