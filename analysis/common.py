"""Shared loading and output helpers for all analysis scripts."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "stories_transactions.csv"
FIG = ROOT / "figures"
OUT = ROOT / "results"
FIG.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

REV = "Line Revenue (USD)"
GP = "Line Gross Profit (USD)"
PRICE = "Unit Price (USD)"
COST = "Unit Cost (USD)"
BRANCHES = ["Harbour", "Garden", "Uptown"]
COLORS = {"Harbour": "#2b6cb0", "Garden": "#c05621", "Uptown": "#718096"}


def load():
    d = pd.read_csv(DATA)
    d["dt"] = pd.to_datetime(d["Date"])
    d["month"] = d["dt"].dt.month
    d["hour"] = d["Time"].str[:2].astype(int)
    d["weekday"] = d["dt"].dt.day_name()
    d["cogs"] = d[COST] * d["Quantity"]
    d["list_rev"] = d[PRICE] * d["Quantity"]
    d["discounted"] = d["Discount Rate"] > 0
    return d


class Log:
    """Print to console and keep a copy in results/<name>.txt so every number is inspectable."""

    def __init__(self, name):
        self.path = OUT / f"{name}.txt"
        self.path.write_text("", encoding="utf-8")

    def __call__(self, *parts):
        text = " ".join(str(p) for p in parts)
        print(text)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def table(self, title, df):
        self(f"\n## {title}")
        self(df.to_string())
