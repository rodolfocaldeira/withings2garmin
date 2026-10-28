# withings2garmin

Small toolkit for moving body-weight history from a Withings export into Garmin Connect, and for cleaning up bad weigh-ins that a unit mix-up (kg vs. lb) left behind.

There are two independent pieces:

1. **Convert** a Withings CSV export into Garmin's "Body" import format (`withings_to_garmin.py`).
2. **Clean up** bad weigh-ins already in Garmin Connect (`cleanup_weighins.py`, Python).

## Workflow

### 1. Export from Withings

Download your data from Withings (Health Mate → Profile → *Download my data*). The weight file must have these columns:

```
Date,"Weight (kg)","Fat mass (kg)","Bone mass (kg)","Muscle mass (kg)","Hydration (kg)",Comments
"2026-03-18 08:45:51",73.73,,,,,
```

### 2. Convert to Garmin format

```sh
python3 withings_to_garmin.py data/wi_weight.csv data/garmin_upload.csv
# or let it pick the output name:
python3 withings_to_garmin.py data/wi_weight.csv   # writes garmin_upload.<yyyymmdd-hhmmss>.csv in the current directory
```

`withings_to_garmin.py` takes the Withings export as its input and writes the Garmin file to the output path. If you leave out the output, it creates `garmin_upload.<yyyymmdd-hhmmss>.csv` in the current directory. It exits with status 1 and prints an error if the input can't be read. For each row it:

- splits the timestamp into `date` and `time`
- computes BMI from a hard-coded height (**173 cm**, the third argument of `convertWithingsToGarmin`; change it to yours)
- computes body-fat % as `fat mass / weight * 100` (`0.0` when fat mass is missing)
- prepends the `Body` line Garmin requires

Output format:

```
Body
weight,bmi,fat,date,time
73.73,24.6,0.0,2026-03-18,08:45:51
```

> **Units:** the weight is written in **kg as-is**. The kg→lb conversion is commented out. Garmin interprets the `weight` column according to the unit set in your Garmin account, so check that setting before importing. Importing values in the wrong unit is exactly what produced the bad entries that `cleanup_weighins.py` removes.

### 3. Import into Garmin Connect

Upload the generated CSV at <https://connect.garmin.com/modern/import-data>.

Check a few entries afterwards, especially the weights.

## Cleaning up bad weigh-ins

`cleanup_weighins.py` finds weigh-ins in Garmin Connect above a threshold (default 105 kg), backs them up, and deletes them.

### Setup

Requires Python >= 3.12.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # garminconnect==0.3.20
```

### Usage

```sh
# Dry run (default): fetch, export, show what would be deleted. Nothing is deleted.
python cleanup_weighins.py

# Actually delete (asks you to type DELETE to confirm)
python cleanup_weighins.py --execute

# Try it on a few entries first
python cleanup_weighins.py --execute --max-delete 3
```

Options: `--yes` (skip the confirmation), `--delay SECONDS` (pause between API calls, default 1.0), `--tokenstore DIR` (default `$GARMINTOKENS` or `~/.garminconnect`), `-v` (verbose).

### Login

Saved tokens are reused when available. Otherwise the script logs in with `GARMIN_EMAIL` / `GARMIN_PASSWORD` (or prompts for them) and asks for an MFA code if needed, then saves the tokens to the token store.

### Configuration

Constants at the top of the script:

| Constant | Default | Meaning |
| --- | --- | --- |
| `START_DATE` | 2018-01-01 | Start of the date range scanned |
| `END_DATE` | 2026-03-10 | End of the range; later entries are assumed clean and are never touched |
| `THRESHOLD_KG` | 105.0 | Entries heavier than this are selected for deletion |
| `MAX_SELECTED_FRACTION` | 0.90 | Abort if more than this share of entries is selected |

Adjust these to your own data before running with `--execute`.

### Safety

- Dry run by default, with an explicit confirmation before deleting.
- Aborts if any selected entry is under the threshold or outside the date range, if too large a fraction is selected, or if the API values don't look like grams.
- Every entry is re-checked immediately before deletion.
- Rate limits and transient errors are retried with backoff. Five consecutive failures stop the run, and it can be re-run to resume.

### Files it produces

| File | Contents |
| --- | --- |
| `data/all_weighins.csv` | Full export of the scanned range. The previous export is kept as `data/all_weighins.<timestamp>.csv`. |
| `data/backup_deleted_weighins.csv` | Backup of every entry selected for deletion, merged across runs. Use it to restore anything deleted by mistake. |
| `data/deletion_log.csv` | One row per delete attempt (`deleted`, `already_gone` or `failed: ...`). |

## Other files

| File | Notes |
| --- | --- |
| `data/withings_data.csv`, `data/wi_weight.csv`, `data/w3.csv`, `data/garmin_upload.csv` | Sample and working data for the converter. |

All CSV files live in `data/`, which the scripts create when needed. The cleanup script's output files go there too.

## Privacy

The CSV files hold personal health data. Don't commit or share them. `.gitignore` already excludes `*.csv`, so the files in `data/` stay out of git.
