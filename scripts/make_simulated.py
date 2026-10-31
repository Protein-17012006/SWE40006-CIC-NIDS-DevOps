"""Derive a simulated real-traffic file from one CSE-CIC-IDS2018 day file (design section 5.5).

The result looks like a different capture tool's output: CIC-IDS2017 column names with their
leading spaces, ISO timestamps, two new columns and no label. Full files are never committed.

    python -m scripts.make_simulated SOURCE OUT [--rows N] [--seed S]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RENAMES: dict[str, str] = {
    "Dst Port": "Destination Port",
    "Tot Fwd Pkts": "Total Fwd Packets",
    "Tot Bwd Pkts": "Total Backward Packets",
    "TotLen Fwd Pkts": "Total Length of Fwd Packets",
    "TotLen Bwd Pkts": "Total Length of Bwd Packets",
    "Flow Byts/s": "Flow Bytes/s",
    "Flow Pkts/s": "Flow Packets/s",
    "Fwd Pkt Len Max": "Fwd Packet Length Max",
    "Fwd Pkt Len Min": "Fwd Packet Length Min",
    "Bwd Pkt Len Max": "Bwd Packet Length Max",
    "Bwd Pkt Len Min": "Bwd Packet Length Min",
    "Init Fwd Win Byts": "Init_Win_bytes_forward",
    "Init Bwd Win Byts": "Init_Win_bytes_backward",
}
COUNTRIES = ("US", "DE", "FR", "GB", "NL", "VN", "SG", "JP", "BR", "AU")
SOURCE_TIMESTAMP = "%d/%m/%Y %H:%M:%S"
_CHUNK = 200_000


def _data_chunks(source: Path) -> "pd.io.parsers.TextFileReader":
    return pd.read_csv(source, dtype=str, keep_default_na=False, chunksize=_CHUNK)


def _without_repeated_headers(chunk: pd.DataFrame) -> pd.DataFrame:
    return chunk[chunk["Label"] != "Label"]


def make_simulated(source: Path, out: Path, rows: int = 100_000, seed: int = 7) -> int:
    total = sum(len(_without_repeated_headers(c)) for c in _data_chunks(source))
    if rows > total:
        raise ValueError(f"{source.name} has only {total} data rows; asked for {rows}")
    rng = np.random.default_rng(seed)
    wanted = np.sort(rng.choice(total, size=rows, replace=False))

    picked, offset = [], 0
    for chunk in _data_chunks(source):
        chunk = _without_repeated_headers(chunk).reset_index(drop=True)
        local = wanted[(wanted >= offset) & (wanted < offset + len(chunk))] - offset
        picked.append(chunk.iloc[local])
        offset += len(chunk)
    df = pd.concat(picked, ignore_index=True).drop(columns=["Label"])

    stamps = pd.to_datetime(df["Timestamp"], format=SOURCE_TIMESTAMP)
    df["Timestamp"] = stamps.dt.strftime("%Y-%m-%d %H:%M:%S")
    df["pkt_entropy"] = np.round(rng.uniform(0, 8, size=rows), 4)
    df["geo_country"] = rng.choice(COUNTRIES, size=rows)
    df = df.iloc[np.argsort(stamps.to_numpy(), kind="stable")]

    columns = [RENAMES.get(c, c) for c in df.columns]
    df.columns = [columns[0], *(f" {c}" for c in columns[1:])]
    df.to_csv(out, index=False, lineterminator="\n")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.make_simulated", description=__doc__)
    parser.add_argument("source", type=Path, help="a CSE-CIC-IDS2018 day file")
    parser.add_argument("out", type=Path, help="where to write the simulated file")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    written = make_simulated(args.source, args.out, rows=args.rows, seed=args.seed)
    print(f"wrote {written} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
