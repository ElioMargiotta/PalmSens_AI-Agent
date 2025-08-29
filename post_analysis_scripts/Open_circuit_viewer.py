"""
Plot Open-Circuit Potential (OCP) experiments.

Each *subfolder* under a root directory (set in .env) is one experiment.
In each experiment folder there can be any number of CSV files.

For every experiment, this script will:
  1) Plot all individual curves overlaid.
  2) Resample all curves onto a common time grid, compute the average and std, and plot mean ± std.
     It also saves the averaged data to CSV.

Root directory:
  - Read from the .env key: OCP_EXPERIMENTS_DIR
  - Or override with CLI: --root "D:/data/ocp"

CSV assumptions:
- We auto-detect time and potential columns using common names.
- If nothing matches, we fall back to the first two numeric-looking columns.
- We handle both comma and semicolon separators, and decimal commas if needed.

Outputs (per experiment):
  <experiment>/ocp_plots/
    overlay.png         # all raw curves overlay
    average.png         # mean ± std of resampled curves
    average.csv         # time, mean, std, n_curves

Run:
  python plot_ocp.py [--root "D:/data/ocp"]

Dependencies: pandas, numpy, matplotlib, python-dotenv
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import math
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# -----------------------------
# Configuration
# -----------------------------
ENV_KEY = "OCP_EXPERIMENTS_DIR"



@dataclass
class Curve:
    name: str
    t: np.ndarray
    y: np.ndarray


# -----------------------------
# Root discovery
# -----------------------------
def find_root_dir(cli_root: Optional[str]) -> str:
    load_dotenv()  # load .env in cwd
    root = cli_root or os.getenv(ENV_KEY)
    if not root:
        raise SystemExit(
            f"Root directory not found. Pass --root or set {ENV_KEY} in your .env"
        )
    if not os.path.isdir(root):
        raise SystemExit(f"Root path does not exist or is not a directory: {root}")
    return root


def list_experiment_dirs(root: str) -> List[str]:
    try:
        entries = [os.path.join(root, d) for d in os.listdir(root)]
    except FileNotFoundError:
        raise SystemExit(f"Root directory not found: {root}")
    return sorted([p for p in entries if os.path.isdir(p)])


# -----------------------------
# CSV reading (robust)
# -----------------------------
def _bom_guess(path: str) -> Optional[str]:
    with open(path, "rb") as f:
        sig = f.read(4)
    if sig.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if sig.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if sig.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return None


def read_csv_auto(path: str, **kwargs) -> pd.DataFrame:
    # Try BOM-based encoding first, then fallbacks
    first = _bom_guess(path)
    guesses = [e for e in [first, "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-8", "cp1252", "latin-1"] if e]
    tried = []
    for enc in guesses:
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except UnicodeDecodeError as e:
            tried.append((enc, str(e)))
            continue

    # last resort: binary -> manual decode attempts
    with open(path, "rb") as fb:
        data = fb.read()
    for enc in ["utf-16", "utf-16-le", "utf-16-be", "utf-8", "latin-1"]:
        try:
            text = data.decode(enc, errors="strict")
            return pd.read_csv(io.StringIO(text), **kwargs)
        except Exception:
            continue
    raise UnicodeError(f"Failed to decode {path}. Tried: {tried}")


def read_csv_smart(path: str) -> pd.DataFrame:
    """Read CSV with robust delimiter/decimal handling."""
    try:
        df = read_csv_auto(path, sep=None, engine="python")
    except Exception:
        df = read_csv_auto(path)

    # If nothing parsed as numeric, try decimal comma
    if not any(pd.api.types.is_numeric_dtype(t) for t in df.dtypes):
        try:
            df2 = read_csv_auto(path, sep=None, engine="python", decimal=",")
            if any(pd.api.types.is_numeric_dtype(t) for t in df2.dtypes):
                df = df2
        except Exception:
            pass
    return df


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [" ".join(str(c).strip().split()).lower() for c in df.columns]
    return df


def pick_time_potential(df: pd.DataFrame) -> Tuple[str, str]:
    """
    Simplest selector:
      - Take the first two numeric-looking columns (after coercion).
      - First -> time, second -> potential.
    """
    df_num = df.apply(pd.to_numeric, errors="coerce")
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df_num[c])]

    if len(numeric_cols) < 2:
        raise ValueError("Need at least two numeric columns to infer time and potential.")

    return numeric_cols[0], numeric_cols[1]




def load_curve_from_csv(path: str) -> Curve:
    df = read_csv_smart(path)
    df = normalize_columns(df)
    time_col, pot_col = pick_time_potential(df)

    t = pd.to_numeric(df[time_col], errors="coerce").to_numpy()
    y = pd.to_numeric(df[pot_col], errors="coerce").to_numpy()

    mask = np.isfinite(t) & np.isfinite(y)
    t, y = t[mask], y[mask]

    if t.size == 0:
        raise ValueError(f"No valid numeric data in {os.path.basename(path)}")

    # Sort by time and drop duplicate timestamps
    order = np.argsort(t)
    t, y = t[order], y[order]
    if t.size > 1:
        uniq = np.empty_like(t, dtype=bool)
        uniq[0] = True
        uniq[1:] = np.diff(t) != 0
        t, y = t[uniq], y[uniq]

    name = os.path.splitext(os.path.basename(path))[0]
    return Curve(name=name, t=t, y=y)


# -----------------------------
# Averaging
# -----------------------------
def build_common_grid(curves: List[Curve]) -> np.ndarray:
    t_min = max(float(c.t.min()) for c in curves)
    t_max = min(float(c.t.max()) for c in curves)
    if not math.isfinite(t_min) or not math.isfinite(t_max) or t_max <= t_min:
        raise ValueError("Time ranges do not overlap across curves; cannot average.")

    med_dts = [float(np.median(np.diff(c.t))) for c in curves if c.t.size >= 2]
    dt = max(med_dts) if med_dts else 1.0
    if dt <= 0:
        dt = 1.0

    n = max(2, int(np.floor((t_max - t_min) / dt)) + 1)
    return np.linspace(t_min, t_max, n)


def resample_to_grid(curves: List[Curve], grid: np.ndarray) -> np.ndarray:
    ys = [np.interp(grid, c.t, c.y) for c in curves]
    return np.vstack(ys)  # (n_curves, n_time)


# -----------------------------
# Plotting & Saving
# -----------------------------
def ensure_outdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def plot_overlay(exp_name: str, curves: List[Curve], outdir: str) -> str:
    ensure_outdir(outdir)
    plt.figure(figsize=(9, 5))
    for c in curves:
        plt.plot(c.t, c.y, label=c.name, alpha=0.8)
    plt.xlabel("Time")
    plt.ylabel("Potential")
    plt.title(f"OCP — {exp_name}: individual curves")
    plt.grid(True, alpha=0.3)
    plt.legend(loc="center left", bbox_to_anchor=(1, 0.5), frameon=False)
    plt.tight_layout()
    out = os.path.join(outdir, "overlay.png")
    plt.savefig(out, dpi=150)
    plt.close()
    return out


def plot_average(exp_name: str, grid: np.ndarray, Y: np.ndarray, outdir: str) -> str:
    ensure_outdir(outdir)
    mean = Y.mean(axis=0)
    std = Y.std(axis=0, ddof=1) if Y.shape[0] > 1 else np.zeros_like(mean)
    plt.figure(figsize=(9, 5))
    plt.plot(grid, mean, label="mean")
    if Y.shape[0] > 1:
        plt.fill_between(grid, mean - std, mean + std, alpha=0.2, label="±1σ")
    plt.xlabel("Time")
    plt.ylabel("Potential")
    plt.title(f"OCP — {exp_name}: average (common grid)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    out = os.path.join(outdir, "average.png")
    plt.savefig(out, dpi=150)
    plt.close()
    return out


def save_average_csv(grid: np.ndarray, Y: np.ndarray, outdir: str) -> str:
    ensure_outdir(outdir)
    mean = Y.mean(axis=0)
    std = Y.std(axis=0, ddof=1) if Y.shape[0] > 1 else np.zeros_like(mean)
    df = pd.DataFrame({"time": grid, "mean": mean, "std": std, "n_curves": Y.shape[0]})
    out = os.path.join(outdir, "average.csv")
    df.to_csv(out, index=False)
    return out


# -----------------------------
# Main processing
# -----------------------------
def process_experiment(exp_path: str) -> None:
    exp_name = os.path.basename(exp_path.rstrip("/\\"))
    csvs = sorted(glob.glob(os.path.join(exp_path, "*.csv")))
    if not csvs:
        print(f"[WARN] No CSV files in {exp_name}. Skipping.")
        return

    curves: List[Curve] = []
    errors = []
    for p in csvs:
        try:
            curves.append(load_curve_from_csv(p))
        except Exception as e:
            errors.append((os.path.basename(p), str(e)))

    if not curves:
        print(f"[WARN] No valid curves in {exp_name}. Errors: {errors}")
        return

    outdir = os.path.join(exp_path, "ocp_plots")

    overlay_path = plot_overlay(exp_name, curves, outdir)

    # Average
    try:
        grid = build_common_grid(curves)
        Y = resample_to_grid(curves, grid)
        avg_plot = plot_average(exp_name, grid, Y, outdir)
        avg_csv = save_average_csv(grid, Y, outdir)
    except Exception as e:
        avg_plot = ""
        avg_csv = ""
        print(f"[WARN] Average failed for {exp_name}: {e}")

    # Manifest
    manifest = {
        "experiment": exp_name,
        "root": exp_path,
        "n_csv": len(csvs),
        "used_files": [os.path.basename(c) for c in csvs],
        "overlay_plot": os.path.relpath(overlay_path, exp_path),
        "average_plot": os.path.relpath(avg_plot, exp_path) if avg_plot else None,
        "average_csv": os.path.relpath(avg_csv, exp_path) if avg_csv else None,
        "errors": errors,
    }
    ensure_outdir(outdir)
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[OK] {exp_name}: overlay → {overlay_path}")
    if avg_plot:
        print(f"      average → {avg_plot}")
        print(f"      data    → {avg_csv}")


def main():
    parser = argparse.ArgumentParser(description="Plot OCP experiments (overlay + average)")
    parser.add_argument("--root", type=str, default=None, help="Root folder with experiment subfolders")
    args = parser.parse_args()

    root = find_root_dir(args.root)
    exps = list_experiment_dirs(root)
    if not exps:
        raise SystemExit(f"No experiment subfolders found in: {root}")

    print(f"Found {len(exps)} experiments under {root}")
    for exp in exps:
        process_experiment(exp)


if __name__ == "__main__":
    main()
