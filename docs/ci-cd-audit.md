# CI/CD audit — personalWiki

**Baseline result:** red. The checked-out CI was aimed at an old .NET solution, while the repository's documented application and container are Python. The remediation below makes Python/pytest/Docker authoritative; deployment remains intentionally separate because no registry or hosting target was specified.

**Audit date:** 2026-08-29 (Europe/Vienna)  
**Local scope:** branch `relentless/consolidate-claude-md-rules`, commit `f7a15c9c134b1703195ae15051cdd4368602753a`.  
**Comparison scope:** the `main` branch of the official [getsentry/sentry-dotnet workflow directory](https://github.com/getsentry/sentry-dotnet/tree/main/.github/workflows), observed on the audit date. Sentry's repository is used for patterns, not as a template to copy wholesale.  
**Audit snapshot:** this report records the pre-remediation state. The follow-up implementation in this working tree updates the Python CI/CD pipeline, dependency controls, security checks, and runtime safeguards. No credential or token value was read or reproduced.

## Remediation applied

- `.github/workflows/ci.yml` now runs pinned-action static checks, deterministic pytest with a 60% coverage floor, an opt-in integration job, Docker Compose smoke checks on pull requests and `main`, and a final CI gate.
- `.github/workflows/extended.yml` runs the complete configured suite manually and on a weekly schedule, including model-backed and external tests.
- `.github/dependabot.yml` updates pip, Docker, the `.opencode` npm lockfile, and GitHub Actions dependencies on separate schedules. `.github/workflows/dependency-review.yml` blocks new high-severity dependency findings.
- `.github/workflows/security.yml` adds scheduled Python CodeQL, Python/npm dependency-audit adapters, and a final security gate. Workflow actions are pinned to full commit SHAs and read-only permissions by default.
- `.github/workflows/main.yml` runs the same pinned PR-Agent review contract as ImmoAgent. It posts advisory review feedback while fork PRs remain credential-free; deterministic CI, security, and dependency checks remain the merge authority.
- Runtime CI inputs no longer require a checked-in `.env`: `.env.example` is a placeholder template, Compose treats `.env` as optional, and CI mounts an isolated vault directory.
- The obsolete .NET solution/test manifests were removed because their referenced `src/` projects are absent; this does not remove any active Python product code.
- Direct and transitive Python dependencies are locked: [`requirements.lock.txt`](../requirements.lock.txt) and [`requirements-dev.lock.txt`](../requirements-dev.lock.txt) (generated with `uv pip compile --universal`); CI, the security audit, and the Docker build install from them. The Docker base image is pinned by digest in both stages of [`Dockerfile`](../Dockerfile).

## Priority summary

Priority meanings: **P0** blocks trustworthy CI/CD; **P1** materially weakens merge or supply-chain confidence; **P2** is important once the core pipeline is healthy. Findings below describe the pre-remediation snapshot; inspect the current workflow files and git diff for the applied controls.

| Priority | Finding | Evidence and impact | Recommended outcome |
| --- | --- | --- | --- |
| P0 | CI targets missing .NET projects | [`ci.yml`](../.github/workflows/ci.yml#L15-L27) restores/builds/tests `Vke.sln`; the solution references `src/Vke.Core` and `src/Vke.Cli` ([`Vke.sln`](../Vke.sln#L6-L12)), but no `src/` directory exists in this checkout. A local `dotnet restore` emitted `MSB3202` for both missing project files. | Replace the .NET job with Python setup, dependency installation, compilation, and pytest; remove or deliberately restore the stale .NET surface in a separate change. |
| P0 | Docker smoke test cannot validate this service | [`docker-compose.yml`](../docker-compose.yml#L4-L9) maps host `8010` to container `8000` and requires `.env`; [`ci.yml`](../.github/workflows/ci.yml#L36-L43) curls `localhost:8080` and does not create `.env` or set `VAULT_PATH`. The service therefore either cannot start on a clean runner or is probed on the wrong port. | Use a temporary runner vault, a non-secret smoke-test environment, `docker compose`, a retry loop against `127.0.0.1:8010`, always collect logs, and always tear down. |
| P1 | Python tests, coverage, and lint are absent from CI | The repository documents Python/pytest ([`CLAUDE.md`](../CLAUDE.md#L100-L131)) and contains a Python test suite, but the workflow invokes only `dotnet test`. There is no coverage package/configuration, coverage upload, threshold, ruff/Black/mypy/pyright check, or test artifact. | Make the full or intentionally partitioned pytest suite a required check; add coverage reporting/thresholds and a selected Python formatter/linter. |
| P1 | Dependency update and lockfile controls are absent | The only dependency manifest is [`requirements.txt`](../requirements.txt#L1-L25); five entries at lines 21–25 are unconstrained, and no Python lock/constraints file, `.github/dependabot.yml`, or package-tool configuration is present. | Choose a lock-producing tool, lock direct and transitive versions, pin all direct requirements, and configure Dependabot for `pip`, Docker, and GitHub Actions. |
| P1 | Workflow supply-chain and token permissions are under-specified | Every local action reference is a mutable tag ([`ci.yml`](../.github/workflows/ci.yml#L13-L34), [`cleanup-audit.yml`](../.github/workflows/cleanup-audit.yml#L8-L18)); neither workflow has an explicit `permissions` block. GitHub recommends least-privilege `GITHUB_TOKEN` permissions and full-length SHA pinning ([secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use?learn=getting_started&learnProduct=actions)). | Pin third-party actions to verified full commit SHAs, retain version comments, set read-only defaults, and grant writes only to a narrowly scoped trusted job. |
| P1 | The audit workflow has an unnecessary write path | [`cleanup-audit.yml`](../.github/workflows/cleanup-audit.yml#L13-L21) runs PR code's scanner with `--fix` and invokes `git-auto-commit-action` with `auto_push: true`; its `push` trigger can run again after a bot commit. Effective token rights are not documented in the file. | Make pull-request auditing read-only and fail/report findings; if auto-fixes are retained, isolate them to a trusted, explicitly authorized workflow and prevent recursion. |
| P1 | Security-alert coverage is not represented in source | There is no CodeQL, dependency-review, image scan, or scheduled vulnerability workflow in local `.github`; alert state cannot be inferred from a checkout. GitHub recommends enabling Dependabot alerts, secret scanning/push protection, and code scanning for a public repository ([security settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)). | Enable repository security features and verify their alert state in GitHub Settings/API; add Python CodeQL and dependency-review checks as appropriate. |
| P1 | Main-branch enforcement is unknown | Branch protection and rulesets are GitHub repository settings, not files in this checkout; no local evidence says that CI is required before merging `main`. | Protect `main` with PR review, required CI/Docker checks, stale-review dismissal, conversation resolution, and force-push/deletion restrictions. |
| P2 | There is no release, registry push, or deployment | The Docker job builds locally and stops the container ([`ci.yml`](../.github/workflows/ci.yml#L29-L46)); it never pushes an image or deploys it. | Decide whether this is a local/self-hosted service. If production deployment is intended, add a separate trusted promotion workflow with environment approval, immutable image references, and provenance. |

## What runs today

### Baseline `CI` (`.github/workflows/ci.yml`)

- It runs on pushes to `main` and pull requests targeting `main` ([lines 3–7](../.github/workflows/ci.yml#L3-L7)); there is no manual or scheduled trigger.
- The `test` job installs .NET `10.0.x`, restores `Vke.sln`, builds it, and runs `dotnet test` ([lines 10–27](../.github/workflows/ci.yml#L10-L27)). This does not exercise the Python runtime described in the repository documentation, and the referenced `src/` projects are absent.
- The `build-docker` job is gated to a push on `main`, waits for `test`, builds an image, runs Compose, probes `localhost:8080`, and stops Compose ([lines 29–46](../.github/workflows/ci.yml#L29-L46)). Pull requests do not receive a Docker smoke test.
- The image is built once with a SHA tag and then Compose builds the service again from `build: .`; the first tag is not consumed by Compose. This is wasted build time and does not produce a registry artifact.

### Baseline `Hallucination Audit` (`.github/workflows/cleanup-audit.yml`)

- It runs for every push and pull request ([lines 1–2](../.github/workflows/cleanup-audit.yml#L1-L2)), unlike `CI`, which is limited to `main` pushes and `main` pull requests.
- It executes a repository Python script with `--fix` ([lines 13–14](../.github/workflows/cleanup-audit.yml#L13-L14)). The script recursively scans Python files and writes changes when it finds selected patterns ([`hallucination_remover.py`](../scripts/hallucination_remover.py#L64-L81)).
- It then calls a third-party auto-commit action with `auto_push: true` ([lines 17–21](../.github/workflows/cleanup-audit.yml#L17-L21)). This is an inappropriate default for a PR quality check: a check should report or fail, not silently rewrite and push the contributor's branch.
- There is no `permissions`, `timeout-minutes`, `concurrency`, path filter, or explicit failure policy. The job can also retrigger on its own push and does not define a safe boundary around files it may modify.

## Repository/runtime mismatch

The repository identifies the product as a FastAPI/HTMX Python application and documents Python 3.13 plus pytest ([`CLAUDE.md`](../CLAUDE.md#L100-L131)); its container runs `uvicorn app:app` on port 8000 ([`Dockerfile`](../Dockerfile#L54-L67)). The active tracked solution and C# test projects are a separate, stale .NET surface: [`Vke.sln`](../Vke.sln#L6-L12) points at `src/`, while the test projects reference `src/Vke.Core/Vke.Core.csproj` ([core test project](../tests/Vke.Core.Tests/Vke.Core.Tests.csproj#L22-L24), [E2E project](../tests/Vke.E2e.Tests/Vke.E2e.Tests.csproj#L24-L26)).

The source of truth for the delivery pipeline must be chosen before adding more checks:

1. For the current product, make Python/pytest/Docker authoritative and mark the C# artifacts as obsolete or restore their complete source tree.
2. Do not call a green .NET job evidence that the FastAPI application works.
3. Keep network-dependent, LLM-dependent, and browser-heavy tests in an explicitly named integration job, with deterministic unit tests as the required fast check.

## Dependency, reproducibility, and update controls

### Baseline local state

- [`requirements.txt`](../requirements.txt#L1-L25) pins most top-level packages with `==`, but `sentence-transformers`, `openai-whisper`, `python-docx`, `markdown`, and `mcp` have no version constraint (lines 21–25).
- There is no `pyproject.toml`, `uv.lock`, `poetry.lock`, `Pipfile.lock`, pip-compile output, `requirements-dev.txt`, or constraints/hashed requirements file in the checkout. There is also no `.github/dependabot.yml`; the only tracked `.github` files are the two workflows cited above.
- The .NET test project files contain package versions ([core](../tests/Vke.Core.Tests/Vke.Core.Tests.csproj#L10-L16), [E2E](../tests/Vke.E2e.Tests/Vke.E2e.Tests.csproj#L10-L18)), but no NuGet lockfile or `global.json` exists. Since their source projects are absent, treat these as stale until the repository ownership decision is made.
- [`Dockerfile`](../Dockerfile#L1-L20) uses floating `python:3.13-slim` tags in both stages; its apt packages are unpinned ([lines 24–45](../Dockerfile#L24-L45)). This makes a rebuild depend on mutable base/package state even where Python requirements are pinned.

GitHub's dependency graph is built from manifests and lockfiles; its documentation recommends lockfiles because they describe the exact direct and transitive versions, and notes that indirect dependencies inferred only from manifests are excluded from vulnerability checks ([dependency graph data](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-graph-data)). GitHub recognizes `requirements.txt` for pip and `.yml`/`.yaml` workflow files as supported dependency inputs ([supported ecosystems/manifests](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-manifests-for-dependency-scope)).

### Recommended control

Use one Python dependency strategy (for example, a lock-producing pip-compatible tool) and commit its lockfile. Keep development/test tools separate from runtime requirements, make CI install from the lock, and update all direct requirements to explicit versions. Then add a `.github/dependabot.yml` covering:

- `pip` at `/` for `requirements*.txt`/the chosen Python manifest;
- `docker` at `/` for the `Dockerfile` base image;
- `github-actions` at `/` for workflow action references; and
- `docker-compose` only if Compose dependency updates are desired.

Dependabot configuration belongs at `.github/dependabot.yml`/`.yaml` and requires a version, updates list, ecosystem, directory, and schedule ([Dependabot configuration](https://docs.github.com/en/code-security/concepts/supply-chain-security/about-the-dependabot-yml-file)). GitHub's version-update example covers Docker and GitHub Actions in addition to package managers ([version updates](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-version-updates)).

## Baseline tests, coverage, and lint

The local test contract is pytest ([`CLAUDE.md`](../CLAUDE.md#L110-L131)); [`pytest.ini`](../pytest.ini#L1-L2) only sets asyncio mode. The current workflow does not install Python, run pytest, collect coverage, upload results, or enforce a threshold. Although the documentation shows `--cov`, `pytest-cov`/`coverage` is not listed in [`requirements.txt`](../requirements.txt#L14-L25). The audit script is a targeted source scan, not a test or linter.

Recommended required checks:

1. **Fast unit job:** install the locked Python environment, compile/import the application, run deterministic tests under `tests/`, and publish JUnit/pytest output on failure.
2. **Coverage:** add an explicit coverage tool, emit a machine-readable report and terminal summary, and set a modest baseline that ratchets upward. Do not count old C# `TestResults` artifacts as current coverage evidence.
3. **Lint/format:** select a maintained Python tool, commit its configuration, run check-only mode on every PR, and fail on violations. Keep auto-fix local or in a separately approved bot workflow.
4. **Integration/E2E:** isolate browser, external-network, LLM, and long-running tests; give them explicit timeouts and fixtures. Keep the required PR path deterministic.
5. **Dependency checks:** run the dependency-review action on PRs after enabling the dependency graph, and add a scheduled vulnerability scan for Python dependencies and the Docker image.

The useful Sentry pattern is the separation of build/test from formatting and vulnerability checks: its [build workflow](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/build.yml) restores, builds, tests, collects XPlat coverage, uploads coverage, archives logs, and runs integration checks; its [format workflow](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/format-code.yml) runs a dedicated `dotnet format` check. For this repository, keep the separation but substitute pytest and a Python formatter/linter.

## Baseline Docker smoke, release, and deployment

### Current failure modes

- The application listens on container port 8000 ([`Dockerfile`](../Dockerfile#L61-L67)) and Compose publishes host port 8010 ([`docker-compose.yml`](../docker-compose.yml#L3-L5)); CI probes 8080 ([`ci.yml`](../.github/workflows/ci.yml#L39-L43)). If the container is healthy, the probe still fails.
- Compose unconditionally includes `.env` ([`docker-compose.yml`](../docker-compose.yml#L8-L13)), while `.env` is ignored ([`.gitignore`](../.gitignore#L1-L10)) and is not created by CI. Docker documents `env_file` as required by default and shows `required: false` as the opt-in behavior for a missing file ([Compose environment files](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)). Use a safe, minimal smoke environment or make the file optional for CI; never put a real credential in the repository.
- Without `VAULT_PATH`, Compose falls back to a macOS iCloud path ([`docker-compose.yml`](../docker-compose.yml#L6-L7)), which is not a portable Linux runner fixture. Set a temporary runner-local directory and mount it read/write only for the smoke job.
- The job uses the legacy `docker-compose` spelling, a fixed five-second sleep, no healthcheck, no retry, no failure logs, and teardown only on the success path ([`ci.yml`](../.github/workflows/ci.yml#L39-L46)). Use the modern `docker compose` command, a bounded retry loop, `docker compose logs` under `if: always()`, and teardown under `if: always()`.
- The current job is not a deployment: it does not log in to a registry, push an image, sign/attest it, or deploy to a runtime. The SHA tag is local to the runner and disappears with it.

Docker's Compose documentation also warns that file references such as `env_file` and bind mounts read host files and can expose their contents during configuration loading ([Compose trust model](https://docs.docker.com/compose/trust-model/)). Keep the smoke fixture synthetic and avoid broad host paths. For a future production path, publish an immutable digest, scan the image, use an environment with approval, and grant only the deployment job registry/deployment permissions.

## Baseline Action pinning, permissions, and workflow security

Local action references are:

- `actions/checkout@v4` and `actions/setup-dotnet@v4` in [`ci.yml`](../.github/workflows/ci.yml#L13-L18) and [`ci.yml`](../.github/workflows/ci.yml#L34);
- `actions/checkout@v4`, `actions/setup-python@v5`, and `stefanzweifel/git-auto-commit-action@v5` in [`cleanup-audit.yml`](../.github/workflows/cleanup-audit.yml#L8-L18).

These are tag references, not immutable commit references. GitHub's security guidance says a full-length commit SHA is the only currently immutable way to pin an action and recommends least privilege for workflow credentials ([secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use?learn=getting_started&learnProduct=actions), [GITHUB_TOKEN permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token)). The current Sentry build, format, and CodeQL sources demonstrate the SHA-plus-version-comment pattern ([build](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/build.yml), [format](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/format-code.yml), [CodeQL](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/codeql-analysis.yml)).

Set an explicit default such as `permissions: contents: read` in read-only workflows. For future publishing/deploying, put write scopes on that job only (for example, package or deployment permissions) and use an environment approval. Do not rely on the repository/org default because the effective default can vary independently of the workflow file.

The `cleanup-audit` write path deserves special treatment. It executes code from a PR checkout, edits files, and asks a third-party action to push. Even if fork PRs receive a read-only token and the push fails, the behavior is brittle; if same-repository PRs or repository defaults grant write access, the path is materially riskier. A read-only audit plus an artifact is sufficient for this repository.

## Branch protection and security-alert verification

No checkout can prove repository-level branch protection, Actions policy, Dependabot alert state, secret-scanning alert state, or CodeQL alert state. The local absence of a workflow is evidence of missing source configuration, not proof that a GitHub UI feature is disabled; conversely, a UI feature cannot repair a broken workflow.

Ask a repository administrator to verify, without pasting credentials into issues or logs:

1. `main` has a pull-request requirement, at least one review, stale-review dismissal, conversation resolution, required status checks for the final Python CI and Docker smoke jobs, and restrictions on force-push and deletion. GitHub lists these controls for protected branches ([protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)) and rulesets ([available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)).
2. Actions defaults are read-only, untrusted PR workflows cannot access production environments, and any full-SHA policy/allowed-actions policy is enabled where feasible. The Actions permissions API documents both default workflow permissions and SHA-pinning policy ([Actions permissions API](https://docs.github.com/en/rest/actions/permissions)).
3. The dependency graph, Dependabot alerts/security updates, secret scanning/push protection, and code scanning are enabled. Dependabot alerts require the dependency graph and are not automatically equivalent to version-update PRs ([Dependabot alerts](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-dependabot-alerts), [security updates](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-security-updates)); GitHub's security-settings guidance calls out Dependabot alerts, secret scanning/push protection, and code scanning as baseline public-repository controls ([security settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)).
4. A PR dependency-review check is required after it is added and pinned. GitHub documents that the dependency-review action can fail a PR when a new dependency has a known vulnerability and can be made a required check ([dependency review](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/customize-dependency-review-action)).
5. The alert dashboards are inspected for open high/critical findings and stale failed analyses. This report intentionally records no alert identifiers, secret names, tokens, or credential values.

For CodeQL, adapt Sentry's explicit job permissions (`actions: read`, `contents: read`, `security-events: write`) and scheduled/push/PR shape from its [CodeQL workflow](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/codeql-analysis.yml), but analyze Python rather than C# and build the actual Python application.

## Sentry workflows: applicable patterns and non-applicable jobs

The official Sentry directory currently lists build, formatting, CodeQL, vulnerability, dependency-update, release, validation, API-verification, mobile-device, Blazor/Playwright, Alpine, changelog, and repository-process workflows ([directory listing](https://github.com/getsentry/sentry-dotnet/tree/main/.github/workflows)). Its breadth reflects a multi-target .NET SDK, native dependencies, NuGet packages, and Sentry's release process. The applicable lessons are the control boundaries, not the exact jobs.

### Patterns worth adapting

| Sentry source | What it demonstrates | Adaptation here |
| --- | --- | --- |
| [`build.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/build.yml) | Separate build, test, coverage, integration, logs, and package outputs across a matrix. | Python unit/integration split, coverage artifact, and Docker smoke; no native/RID/NuGet matrix. |
| [`format-code.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/format-code.yml) | A dedicated PR formatting check. | Add a check-only Python formatter/linter job. |
| [`codeql-analysis.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/codeql-analysis.yml) | Scheduled plus push/PR static analysis with explicit `security-events` permission. | CodeQL Python analysis, only if the repository's CodeQL availability/plan supports it. |
| [`vulnerabilities.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/vulnerabilities.yml) | Manual, daily, and PR vulnerability checks, including transitive package inspection. | Dependabot plus a Python/Docker vulnerability check; use the locked environment. |
| [`update-deps.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/update-deps.yml) | A scheduled/manual dependency-maintenance workflow with explicit write permissions. | Prefer Dependabot for this repo's `pip`, Docker, and Actions inputs; do not copy Sentry's external SDK updater. |
| [`release.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/release.yml) | Manual, controlled SDK release orchestration. | Add only if personalWiki will publish a versioned artifact/image; it is not needed for local Compose use. |

### Explicitly do **not** copy

These Sentry jobs are mobile/.NET/SDK-specific and do not apply to this Python/FastAPI service:

- [`device-tests-android.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/device-tests-android.yml) and [`device-tests-ios.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/device-tests-ios.yml): Android/iOS device and MAUI SDK testing.
- The native, multi-RID, AOT, MAUI trim-analysis, MSBuild, solution-filter, NuGet-pack, and mobile portions of [`build.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/build.yml).
- [`format-code.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/format-code.yml), [`codeql-analysis.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/codeql-analysis.yml), and [`verify-api.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/verify-api.yml) as written: they target C#/.NET solution/API semantics; only their check separation and permissions are relevant.
- [`playwright-blazor-wasm.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/playwright-blazor-wasm.yml): a Sentry Blazor/WebAssembly integration, not the local FastAPI UI.
- [`alpine.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/alpine.yml): builds Sentry's native Alpine image, not this application's runtime image.
- [`update-deps.yml`](https://github.com/getsentry/sentry-dotnet/blob/main/.github/workflows/update-deps.yml): updates Sentry native/Cocoa/Java/CLI SDK modules, not this repository's Python/Docker/Actions dependencies.
- Changelog, Danger, PR-risk, needs-repro, upstream-watch, and Craft/release workflows ([directory](https://github.com/getsentry/sentry-dotnet/tree/main/.github/workflows)) encode Sentry's organization/release process and should not be imported without an equivalent local requirement.

## Redacted credential handling

The local checkout contains an ignored `.env` file, which was not opened or copied into this report; [`.env.example`](../.env.example) is the only tracked environment template. Workflows contain no explicit `${{ secrets.* }}` or `${{ vars.* }}` references. This is not proof that remote Git history or GitHub alert dashboards are clean. If a real credential has ever been committed or exposed in a log, revoke/rotate it through the provider and then investigate the corresponding GitHub alert; this report intentionally omits all values and identifiers.

## Remaining follow-up

Follow-up status recorded 2026-08-31 after the remediation implementation in this working tree:

1. **P1 — make inputs fully reproducible:** done. [`requirements.lock.txt`](../requirements.lock.txt) and [`requirements-dev.lock.txt`](../requirements-dev.lock.txt) pin every direct and transitive dependency (generated with `uv pip compile --universal --python-version 3.13`); CI, the extended suite, the security audit, and the Docker build all install from the lock files. Dependabot's pip ecosystem updates any `.txt` manifest, so the compiled locks stay in sync with `requirements.txt`/`requirements-dev.txt` under the existing `python-dependencies` group. The Docker base image is pinned by digest in both stages of [`Dockerfile`](../Dockerfile) (index of `python:3.13-slim`, Debian trixie, observed 2026-08-31); the builder stage builds cleanly from the lock. The full-image build overflows the local Docker VM disk at the pre-existing Playwright step, not at the lock install; GitHub-hosted runners have ample disk.
2. **P1 — verify repository settings:** verified 2026-08-31 via the GitHub API. Dependabot alerts are enabled (no open alerts), secret scanning is enabled (1 alert), and code scanning/CodeQL is enabled (13 alerts). **Not yet applied:** `main` has no branch protection or ruleset, so the `CI gate`, `Dependency review`, and `Security gate` checks are not yet required; the repository Actions default is `allowed_actions: all` with SHA pinning not required. Apply a protected-`main` ruleset once the new workflows have run on a PR, require the `CI gate`/`Dependency review`/`Security gate` checks, and consider restricting allowed actions.
3. **P2 — only if needed:** design a separate release/deploy workflow with immutable image promotion, environment approval, least-privilege registry/deployment permissions, and build provenance. Still not started; no registry or hosting target has been specified.

## Reuse across projects

If this will serve two or more repositories, move the generic jobs into a
dedicated organization repository (for example, `platform-ci`) as reusable
`workflow_call` workflows. Keep each application repository's workflow as a
small caller that supplies its Python version, test markers, Docker service,
and coverage floor; reference the shared workflow by a release tag or commit
SHA. GitHub documents this caller/callee model and recommends SHA references
for stability ([reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)).

PersonalWiki and ImmoAgent now share the same job IDs (`static`, `test`,
`integration`, `docker`, `gate`, plus the security and PR-review gates) and the
same immutable-action/review policy. Their commands intentionally adapt to
their runtimes: PersonalWiki smoke-tests FastAPI/Docker, while ImmoAgent
type-checks/builds its dashboard and validates MongoDB/Compose.

Keep `.github/dependabot.yml` in each repository because Dependabot reads that
repository's manifests and update policy ([configuration reference](https://docs.github.com/en/code-security/concepts/supply-chain-security/about-the-dependabot-yml-file)). An organization `.github` repository
is useful for templates, CODEOWNERS, and default community files, but it does
not automatically inject a workflow into every existing repository. This
personalWiki pipeline should remain local until the shared contract and owner
repository exist.
