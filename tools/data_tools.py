# data_tools.py

import os, glob, csv
from datetime import datetime

# ─── Force headless (Agg) backend ───
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
# ────────────────────────────────────

def list_experiment_results(pattern: str = "*.csv",
                            directory: str = "results/files") -> list:
    out = []
    for root, _, _ in os.walk(directory):
        out += glob.glob(os.path.join(root, pattern))
    return out

def plot_overlap(files: list, title: str = "overlap_plot") -> str:
    """
    Load multiple CSVs (2-column: potential, current) and plot them overlapped.
    Saves to results/analysis/<title>_<timestamp>.png and returns that path.
    """
    # 1) Guard against empty input
    if not files:
        raise ValueError("plot_overlap: no files provided to plot.")

    curves = []
    for fpath in files:
        xs, ys = [], []
        with open(fpath, newline='') as cf:
            reader = csv.reader(cf)
            header = next(reader)  # skip header row
            for row in reader:
                try:
                    xs.append(float(row[0]))
                    ys.append(float(row[1]))
                except:
                    continue
        curves.append((os.path.basename(fpath), xs, ys))

    # 2) Build the figure
    fig, ax = plt.subplots()
    for name, xs, ys in curves:
        ax.plot(xs, ys, label=name)
    ax.set_title(title)
    ax.set_xlabel("Potential (V)")
    ax.set_ylabel("Current (uA)")
    ax.legend()
    plt.tight_layout()

    # 3) Ensure output dir exists
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("results", "analysis")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{title}_{ts}.png")

    # 4) Save and close
    fig.savefig(out_path)
    plt.close(fig)

    # 5) Confirm to caller
    return out_path

def detect_cv_peaks(files: list,
                    potential_min: float = None,
                    potential_max: float = None) -> dict:
    """
    For each CSV file (two-column: potential, current), find the highest
    (oxidation) and lowest (reduction) current peaks in the optional
    potential window [potential_min, potential_max]. Returns a dict:
      {
        "<filename>": {
          "peak_potential": float, "peak_current": float,
          "trough_potential": float, "trough_current": float
        },
        …
      }
    """
    results = {}
    for fpath in files:
        xs, ys = [], []
        with open(fpath, newline='') as cf:
            reader = csv.reader(cf)
            next(reader, None)  # skip header
            for row in reader:
                try:
                    x = float(row[0]); y = float(row[1])
                except:
                    continue
                if potential_min is not None and x < potential_min:
                    continue
                if potential_max is not None and x > potential_max:
                    continue
                xs.append(x); ys.append(y)
        if not xs:
            continue
        # find oxidation peak (max y) and reduction trough (min y)
        max_idx = ys.index(max(ys))
        min_idx = ys.index(min(ys))
        results[os.path.basename(fpath)] = {
            "peak_potential": xs[max_idx],
            "peak_current": ys[max_idx],
            "trough_potential": xs[min_idx],
            "trough_current": ys[min_idx]
        }
    return results