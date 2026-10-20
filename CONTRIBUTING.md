# Contributing

## Versioning and releases

The app's version lives in [`version.py`](version.py). It appears in the sidebar, at
`GET /version`, and in the User-Agent the app sends to HCPD and other services. **Don't edit it by
hand.** Every merge to `main` runs [python-semantic-release](https://python-semantic-release.readthedocs.io/)
(see [`.github/workflows/release.yml`](.github/workflows/release.yml)), which:

1. Works out the next version from the commits since the last `vX.Y.Z` tag.
2. Updates `version.py` and `CHANGELOG.md`, and commits them as `chore(release): X.Y.Z`.
3. Tags `vX.Y.Z` and creates a GitHub Release.

Releases don't deploy anything. Render, Docker and the Kubernetes deployments are handled
separately; the Docker workflow tags images with the version by default.

## Pull request titles

PRs are **squash-merged**, and the PR title becomes the commit on `main`, so **the PR title
decides the release.** The commits on your branch can say anything. The
[PR title check](.github/workflows/pr-title.yml) enforces this format:

```
<type>(<optional scope>)<optional !>: <summary>
```

| Type | Release |
|---|---|
| `feat` | minor: 1.4.0 → 1.5.0 |
| `fix`, `perf` | patch: 1.4.0 → 1.4.1 |
| any type with `!`, or a `BREAKING CHANGE:` footer | major: 1.4.0 → 2.0.0 |
| `docs`, `test`, `refactor`, `chore`, `ci`, `build`, `style` | no release |

**Scopes** (optional): `referral`, `diagnostic`, `booking`, `filler`, `hcpd`, `pd`, `smart`,
`ui`, `deps`.

Examples:

- `feat(booking): let the placer reschedule into another slot`
- `fix(hcpd): honour Retry-After when it exceeds 120 s`
- `feat(hcpd)!: rename HCPD_BEARER_TOKEN to HCPD_TOKEN`

### What counts as breaking

A change is **breaking** only if **someone has to act when it's deployed**. For example: a
renamed or removed `.env` key, a new required setting, or a data or migration step. Changes to
the FHIR resources the app sends (bundle structure, profiles, elements) are `feat` or `fix`, not
breaking.

## Direct pushes to `main`

Direct pushes are allowed, but they skip the PR title check, so the commit message itself must
follow the format above. A message that doesn't is ignored: that push simply doesn't produce a
release. To catch mistakes locally, enable the commit-msg hook once per clone:

```sh
git config core.hooksPath .githooks
```

## Development

```sh
python -m pip install -r requirements-dev.txt
pytest tests
```

Use `python -m pip` rather than `pip`: a copied virtualenv can have a `pip` script that installs
into a different environment.
