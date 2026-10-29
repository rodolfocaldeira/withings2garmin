#!/usr/bin/env python3
"""Converts Withings CSV data to Garmin-compatible CSV format.

Logic:
1. Reads the Withings CSV.
2. Converts Weight (kg) to lbs (currently disabled; weight is written in kg as-is).
3. Calculates BMI using height (173 cm).
4. Calculates Fat % from Fat mass (kg) and Weight (kg).
5. Formats the date and time.
6. Prepends the "Body" header required by Garmin.

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path


def convert_withings_to_garmin(input_path: Path, output_path: Path, height_cm: float = 173) -> None:
    """Convert a Withings CSV export to Garmin's "Body" import format.

    Args:
        input_path: Path to the Withings CSV file.
        output_path: Path where the Garmin CSV will be saved.
        height_cm: User height in centimeters for BMI calculation.
    """
    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    # Drop fully blank lines, mirroring data.trim().split('\n') in the JS version.
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise ValueError("Input file is empty or missing data.")

    # Header looks like: Date,"Weight (kg)","Fat mass (kg)"...
    headers = [h.strip() for h in rows[0]]
    idx_date = headers.index("Date")
    idx_weight = headers.index("Weight (kg)")
    idx_fat_mass = headers.index("Fat mass (kg)")

    output_rows: list[str] = []
    height_meters = height_cm / 100

    for row in rows[1:]:
        cells = [c.strip() for c in row]

        def cell(idx: int) -> str:
            return cells[idx] if idx < len(cells) else ""

        date_str = cell(idx_date)
        try:
            weight_kg = float(cell(idx_weight))
        except ValueError:
            continue
        try:
            fat_mass_kg = float(cell(idx_fat_mass))
        except ValueError:
            fat_mass_kg = float("nan")

        if not date_str:
            continue

        # 1. Date and Time formatting
        # Withings format: "2026-03-18 08:45:51"
        date_part, _, time_part = date_str.partition(" ")

        # 2. Weight conversion (kg to lbs), disabled as in the original:
        # weight_lbs = weight_kg * 2.20462

        # 3. BMI Calculation: kg / (m^2)
        bmi = f"{weight_kg / (height_meters * height_meters):.1f}"

        # 4. Fat percentage calculation
        fat_percent = "0.0"
        if fat_mass_kg == fat_mass_kg and weight_kg > 0:  # NaN check
            fat_percent = f"{(fat_mass_kg / weight_kg) * 100:.1f}"

        # Print whole numbers without ".0" (matches JavaScript number formatting).
        weight_str = str(int(weight_kg)) if weight_kg.is_integer() else str(weight_kg)
        output_rows.append(f"{weight_str},{bmi},{fat_percent},{date_part},{time_part}")

    # Garmin requires the word "Body" on the first line
    final_csv_content = "\n".join(["Body", "weight,bmi,fat,date,time", *output_rows])

    output_path.write_text(final_csv_content, encoding="utf-8")
    print(f"Successfully converted {len(output_rows)} records to {output_path}")


def default_output_path() -> Path:
    """Return a timestamped name like data/garmin_upload.20261028-171600.csv."""
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / f"garmin_upload.{datetime.now():%Y%m%d-%H%M%S}.csv"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Withings weight CSV export to Garmin's Body import format.",
    )
    parser.add_argument("input", type=Path, help="Withings CSV export to read")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Garmin CSV to write (default: data/garmin_upload.<yyyymmdd-hhmmss>.csv)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = args.output or default_output_path()

    try:
        convert_withings_to_garmin(args.input, output_path, 173)
    except (OSError, ValueError, KeyError) as err:
        print(f"Error converting CSV: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
