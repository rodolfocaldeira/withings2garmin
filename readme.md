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
python3 withings_to_garmin.py data/wi_weight.csv   # writes data/garmin_upload.<yyyymmdd-hhmmss>.csv
```

`withings_to_garmin.py` takes the Withings export as its input and writes the Garmin file to the output path. If you leave out the output, it creates `data/garmin_upload.<yyyymmdd-hhmmss>.csv`. It exits with status 1 and prints an error if the input can't be read. For each row it:

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

## Automatic sync (Withings → Garmin)

`sync_weights.sh` runs the whole pipeline in one command. It downloads recent weigh-ins from the Withings API (`withings_download.py`), then uploads only the ones Garmin Connect doesn't have yet (`upload_new_weighins.py`).

### Setup

1. **Create a Withings app** at <https://developer.withings.com/dashboard> and set its callback URL to `http://localhost:8765/callback`. This is the default redirect URI; if you use another, set `WITHINGS_REDIRECT_URI` to match.
2. **Create a `.env` file** in the project folder with your app's credentials:

   ```
   WITHINGS_CLIENT_ID=your-client-id
   WITHINGS_CLIENT_SECRET=your-client-secret
   WITHINGS_REDIRECT_URI=http://localhost:8765/callback
   ```

   The sync script loads this file automatically. Keep it private; `.gitignore` excludes it.
3. **Install the Garmin library** in the `.venv` virtual environment, as in the cleanup section above:

   ```sh
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

The first Withings download opens your browser so you can approve access. The resulting tokens are saved to `withings_tokens.json`, which is owner-only and gitignored. Garmin login uses the same credentials and token store as `cleanup_weighins.py` (`GARMIN_EMAIL` / `GARMIN_PASSWORD`, or prompts).

### Usage

```sh
# Download the last 7 days and show what would be uploaded. Nothing is uploaded.
./sync_weights.sh

# Download the last 30 days instead
./sync_weights.sh --days 30

# Upload the new weigh-ins (asks you to type UPLOAD)
./sync_weights.sh --execute

# Upload without the confirmation prompt
./sync_weights.sh --execute --yes
```

| Option | Meaning |
| --- | --- |
| `--days N` | Download only the last N days, including today. Default: 7. |
| `--execute` | Upload the missing weigh-ins. Without it, the upload step is a dry run. |
| `--yes` | With `--execute`, skip the `UPLOAD` confirmation. |

### How "already in Garmin" is decided

A Withings weigh-in counts as already present when Garmin has a weigh-in on the same day whose weight differs by at most 0.1 kg. Each Garmin weigh-in can match only one Withings weigh-in, so two genuine same-day readings are not collapsed into one. Everything else is uploaded with its original local time and UTC time.

### Running the scripts individually

```sh
# Download only, to data/withings_weights.csv (overwritten on each run)
.venv/bin/python withings_download.py --days 7

# Compare and upload (dry run unless --execute)
.venv/bin/python upload_new_weighins.py
```

`withings_download.py` also accepts `--since YYYY-MM-DD`, `--until YYYY-MM-DD` and `--reauth` (to log in to Withings again). `upload_new_weighins.py` also accepts `--input`, `--max-upload N` and `--delay SECONDS`.

### Files it produces

| File | Contents |
| --- | --- |
| `data/withings_weights.csv` | Weigh-ins from the last download (`date,time,weight_kg,timestamp,grpid`). Replaced on every run. |
| `data/upload_log.csv` | One row per upload attempt (`uploaded` or `failed: ...`). |
| `withings_tokens.json` | Withings login tokens. Owner-only, gitignored. Delete it or use `--reauth` to log in again. |

## Other files

| File | Notes |
| --- | --- |
| `data/withings_data.csv`, `data/wi_weight.csv`, `data/w3.csv`, `data/garmin_upload.csv` | Sample and working data for the converter. |

All CSV files live in `data/`, which the scripts create when needed. The cleanup script's output files go there too.

## Privacy

The CSV files hold personal health data. Don't commit or share them. `.gitignore` already excludes `*.csv`, so the files in `data/` stay out of git.
