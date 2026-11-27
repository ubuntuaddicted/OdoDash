# ubuntuaddicted/ododash: fork notes

This is a fork of [OdoDash](https://github.com/moshiur-hridoy/OdoDash) (itself a
fork of [May](https://github.com/dannymcc/may)). It adds what a phone needs to
log trips by itself for business mileage records. Everything else is upstream.

## What the fork changes

| Area | Change | Files |
|---|---|---|
| Trips | `start_time`, `end_time` (local clock time) and `gps_distance` (phone GPS, in the vehicle's odometer unit) | `app/models.py` (`Trip`) |
| API | `POST /api/v1/vehicles/<id>/trips` and `PATCH /api/v1/trips/<id>` accept the three fields; every trip response returns them | `app/routes/api.py` (`_parse_trip_fork_fields`) |
| Database | Migration `d0f1a2b3c4e5` adds the three nullable columns | `migrations/versions/d0f1a2b3c4e5_fork_trip_times_gps_distance.py` |
| Tests | Guard the fork's features | `tests/test_fork_*.py` |
| Upstream sync | Weekly PR that merges upstream and reports test results | `.github/workflows/upstream-sync.yml` |

Fork code is marked with `[fork]` comments, so `git grep "\[fork\]"` lists it.

### Rules for fork changes

- **Add, don't rewrite.** New columns, new fields and new helpers. Upstream
  functions change by a single call at most, so upstream merges stay small.
- **Every fork feature has a test in `tests/test_fork_*.py`.** These tests are
  what flag an upstream change that breaks the fork.
- **Odometer readings stay the record of distance.** `distance` is still
  `end_odometer - start_odometer`. `gps_distance` sits next to it and is
  reconciled against real odometer readings from fuel logs.

### API example

```bash
# Leaving: open the trip
curl -X POST https://ododash.example/api/v1/vehicles/1/trips \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"date":"2026-01-31","start_time":"09:37","start_odometer":90971,"purpose":"business","end_location":"Connie, Glendale"}'

# Arriving back: close it
curl -X PATCH https://ododash.example/api/v1/trips/42 \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"end_time":"12:13","end_odometer":91006.5,"gps_distance":35.2}'
```

Send `null` to clear a field. Times may be `HH:MM` or `HH:MM:SS`.

## Getting upstream updates

`upstream-sync.yml` runs every Monday (and can be started from the Actions
tab). It never touches `dev` directly. Each run:

1. Merges the newest upstream `ododash-release` into a new `sync/upstream-<sha>` branch.
2. Runs the full test suite (upstream's tests plus the fork's) on the merged code.
3. Opens a PR into `dev` that shows the test results, flags whether the fork's
   own tests passed, and lists any files that both upstream and the fork changed.
   If tests fail or there are merge conflicts, the PR is opened as a draft.

Merge it once you've reviewed it, or leave it open.

### If upstream adds a migration

The fork's migration and a new upstream migration would both follow the same
parent, and `tests/test_migration_heads.py` would fail. To fix it, check out
the sync branch and run:

```bash
flask db merge heads -m "merge upstream and fork migrations"
```

Commit the new merge migration to the sync branch. Neither existing migration
needs editing.

## Deploying

Run a tagged release of this fork, not `latest` or `dev`. Tag after merging to
`ododash-release` (`v0.44.0-dan.1`, and so on). Rolling back means changing the
image tag back. `docker.yml` publishes images to
`ghcr.io/ubuntuaddicted/ododash`.

## Fork releases

Fork release notes go here rather than in `CHANGELOG.md`, which upstream edits
on every release; fork entries there would conflict on every sync.
`APP_VERSION` in `config.py` stays at the upstream version this fork is based
on, since the sidebar's update check reads it as plain `X.Y.Z`. The fork's own
version is the git tag: `v<upstream version>-dan.<n>`.

### v0.52.0-dan.1 (2026-11-27)

Based on upstream OdoDash 0.52.0.

- Trips: `start_time`, `end_time` and `gps_distance`, in the model, API and migration `d0f1a2b3c4e5`.
- Weekly upstream-sync workflow that opens a tested PR into `dev`.
- `FORK.md` and `tests/test_fork_trip_tracking.py`.
