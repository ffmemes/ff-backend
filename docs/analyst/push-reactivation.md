# Dormant-user push response

A historical example is one accepted reengagement push to an ordinary user with a recorded callback 7–365 days earlier. Its binary outcome is a stored like or dislike on the pushed meme within the next 24 hours. Telegram does not expose a message-open event. A later reaction correction can overwrite the original callback.

## Run the monthly evaluation

The verified fit used Python 3.13.3, NumPy 2.3.5 and scikit-learn 1.7.2. Use a read-only psql connection. Set PGSERVICE to a local analyst service or pass a private psql-compatible adapter after the double dash. Put the output outside Git in a new directory. The following example trains on mature sends before November 1 and tests November 1–14 UTC.

```sh
python3 scripts/analysis/run_push_backtest.py \
  --start 2026-08-10 --holdout-start 2026-11-01 --as-of 2026-11-21 \
  --output "$HOME/.local/share/ffmemes-analysis/2026-11" -- psql -Xq
```

For the next monthly cycle set the holdout start to the first of the new month, the observation cutoff to the 16th, and add `--previous-model /path/to/previous/model.json` before the double dash. The old and new models then score the same mature period. To freeze the next challenger with all currently mature training labels, run separately with holdout start equal to the observation cutoff. The future outcome window will show as pending. A frozen v1 model can also score its compatible columns from v2 data. The runner keeps individual rows in a temporary file and publishes aggregate JSON and frozen coefficients on successful completion. `extraction.json` records the SQL hash. The model records dependency versions and the fit-script hash. Historical tables are mutable, and each SQL batch reads a separate snapshot.

## Interpret the decision

Compare user-plus-content vs user-only log loss. Also inspect the intercept-only model, the reconstructable legacy score, calibration, response by dormancy, and paired within-user AUC with its support. The legacy score is a proxy for historical HQ picks. The training SQL documents which fields were observable at send and how delayed outcomes enter features. Short-term counts and rates use 35 days. V2 adds the most recent 200 genuine feed callbacks within the preceding year. Overall history and like rate enter both personalized models; history with the candidate source enters the content model.

Choose regularization on preceding development folds. Keep the full 24-hour outcome horizon outside every boundary. A candidate only qualifies for prospective shadow measurement if every development fold improves and the lower user-cluster bootstrap bound for final improvement is above zero. Keep the final calendar block fixed while making model decisions. After inspecting a final result, evaluate changes on a fresh period.

The extractor observes the delivered item. Candidate alternatives and the probability of selecting each are absent from historical sends. Validate which meme to send by randomizing between content policies at fixed cadence. For send timing, run `push-reactivation-holdout.sql` with a UTC `as_of` date and evaluate both assigned arms from assignment time, with any callback in 24 hours, a feed callback on days 7–14, and recorded blocks. A send can discover a previously silent block; the holdout lacks that delivery probe. Treat recorded blocks as an operational guardrail and consult the registered 30-day decision rule for the monthly experiment. Repeated monthly evaluations do not authorize switching the live picker or cadence.

Model regressions run with `python3 -m unittest discover -s scripts/analysis -p 'test_push_reactivation_backtest.py'`. SQL regressions run with `PUSH_SQL_TEST_PSQL` pointing to a disposable PostgreSQL test database and `python3 scripts/analysis/test_push_reactivation_sql.py`. The fixture uses temporary relations and rolls back.

## Reuse one local dataset for parameter selection

The private snapshot retains only ordinary, mature reengagement deliveries with an observed idle interval of 7–365 days. Its 26 columns include the label, timing, surface and per-export pseudonyms. User IDs, Telegram content and the ephemeral salt are excluded. Keep the snapshot on protected local storage outside Git and cloud sync. An export with a new salt cannot be joined to the previous one by user. The manifest records the observation boundaries, population, exclusions, row counts and hashes. Corrections to old callbacks can change a later export.

The first matched study uses the first recorded push date, August 9, through November 19 inclusive. The commands below create a new dataset, fit local models and keep their aggregate report outside Git. Use an existing private analyst directory or allow the exporter to create it beneath an existing parent. Use a read-only psql service or pass a private adapter after the double dash.

```sh
umask 077
study_root="$HOME/.local/share/ffmemes-analyst"
python3 scripts/analysis/export_push_snapshot.py --root "$study_root" \
  --name reactivation-20261121 --start 2026-08-09 --end 2026-11-20 \
  --as-of 2026-11-21 -- psql -Xq
snapshot="$study_root/datasets/reactivation-20261121/rows.csv.gz"
run_dir=$(mktemp -d "$study_root/matched-20261121-XXXXXX")
python3 scripts/analysis/compare_push_models.py train --input "$snapshot" \
  --as-of 2026-11-21 --cutoff 2026-11-21 --model-out "$run_dir/model.json" \
  > "$run_dir/report.json"
```

Five models receive identical training and evaluation rows. The recent and long user-only arms measure the contribution of general activity history. The recent full and long full arms add meme and source features. A fifth model includes the user's overall long history and all the recent content features but omits their two long-history features for the candidate's source. The primary contrast is that fifth model's user-averaged log loss minus the long full model's loss. A positive value favors adding source history. Choosing each arm's L2 strength uses mature *earlier* inner folds. Three outer folds estimate performance on later deliveries. Compare the 29+ day and delivery-path diagnostics with their denominators.

Each new matched fit reserves the first 14 UTC days of the next calendar month. Its frozen evaluation dates are derived from the training cutoff. For the November fit the prespecified fresh test is December 1–14, 2026 UTC. On or after December 16, export a new dataset covering that interval and its complete outcome horizon. Evaluate the saved November weights once. For monthly retraining, export one snapshot with sufficient historical coverage and the current UTC observation cutoff. Use the same file to score the prior weights and freeze the next matched fit. Verify the saved data and SQL hashes, then run all model comparisons locally.

```sh
python3 scripts/analysis/compare_push_models.py evaluate \
  --input "$study_root/datasets/reactivation-20261216/rows.csv.gz" \
  --as-of 2026-12-16 --model "$run_dir/model.json" > "$run_dir/december.json"
```

The bounded-shortlist prototype and its pre-dispatch requirements are described in [the serving design](push-reactivation-serving.md). The benchmark accepts the existing single v2 bundle and produces machine-specific timings.

```sh
python3 scripts/analysis/benchmark_push_ranking.py --model /private/v2/model.json \
  --users 256 --repeats 5 --output /private/new-benchmark.json
```

For this matched study, retain the existing stability standard. All three outer estimates must favor the prespecified primary contrast, and the fresh test's paired 95% user-cluster interval must exclude zero in the positive direction before treating the observation as support for a shadow trial. Report the 29+ day subgroup and its uncertainty even when the pooled estimate improves. This is a screening rule for prediction. A positive incremental content-policy effect requires randomized assignments. No model is promoted automatically.
