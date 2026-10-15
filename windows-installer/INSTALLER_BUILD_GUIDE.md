# Windows Dify installer source and build

Integration author: **Letian Kang** — **Letian.Kang@amd.com**.

This is the complete x64 .NET Framework 4.8 / WinForms bootstrapper for Dify
**1.17.1**, installer **1.0.10** and **AMDTokenFactory** dynamic provider **0.0.10**. A prepared build
embeds deployment files, Docker Compose, the reviewed plugin and licenses. Users
still need existing WSL2/Linux Docker and Internet access for first-install
container images. Neither preparation nor the EXE distributes Docker/WSL or
constitutes an official signed AMD/Dify release.

The installer is maintained on the separate `feature/dify-windows-installer`
branch, based on the AMDTokenFactory provider sources. Review its changes against
the corresponding provider changes: the model provider and API compatibility are prerequisites,
not duplicated installer changes. The provider branch itself contains no Windows
bootstrapper source and can be deployed using its standalone API setup.

## Source layout

- `DifySetup.cs`, `build.ps1`: installer/manager, safe payload packing and EXE build.
- `payload/windows/`: WSL runtime, localhost-only Compose overrides, shortcuts,
  manifest and read-only model compatibility helper.
- `payload/LICENSE`, `payload/tools/COMPOSE-LICENSE.txt`,
  `payload/THIRD_PARTY_NOTICES.txt`: tracked redistribution licenses and notices.
- `prepare_payload.sh`: materializes ignored `payload/docker/` from **exactly**
  `8387590ace4a094de812b7847fc6a4c3a27cd52b`, not the current branch or `main`.
  It also generates `payload/api-compat/` from `../api-compat` plus the provider's
  `model_catalog.py`, including the canonical `amdtokenfactory_remote.py`, and
  copies three public guides from `../plugins/amdtokenfactory`. The required
  package is copied as `payload/plugins/AMDTokenFactory-0.0.10.difypkg`.
- `payload/.upstream-commit`, `payload/.prepared.sha256`: generated preparation
  receipts, checked before packing. Package, Compose binary, receipts, upstream
  copies, EXEs, images, environments and caches are not source-controlled.
- `tests/test_installer.py`: offline preparation and runtime-safety regressions.
  `tests/test_windows_bridge.ps1` checks a newly built EXE and the Windows/WSL bridge.

## Prepare first, then build

1. Use the provider's Python 3.12 locked development environment; run its tests,
  lint and package-content check. Supply the reviewed `AMDTokenFactory-0.0.10.difypkg`.
   A freshly repackaged source tree is not automatically the reviewed binary.
2. In Linux/WSL, run `bash windows-installer/prepare_payload.sh /absolute/path/to/AMDTokenFactory-0.0.10.difypkg`.
   Git, GNU coreutils and `flock` are required; `curl` is needed only if Compose
   is missing. The default source repository is the parent checkout. If the exact
   release commit is absent, preparation fetches that full commit ID from the fixed
  `git@github.com:langgenius/dify.git` SSH remote into a temporary bare repository.
  This requires an existing authorized SSH setup and known GitHub host key; it
  does not prompt for credentials or change authentication configuration.
   It never checks out a branch, follows `HEAD`, invokes credential helpers or
  reads private Dify configuration. It accepts only regular Git blobs under `docker/`
   and `LICENSE`, rejects unsafe paths/links and verifies each blob before copying.
3. For **offline preparation**, add `--offline --source-repository /path/to/repository`
   and `--compose /path/to/docker-compose-linux-x86_64`. The repository must already
   contain the pinned commit and all its deployment blobs. Missing objects/inputs
   fail; there is no network or fallback to `main`. Paths may point to separate
   reviewed build inputs; no installed instance or user's `.env` is needed.
4. Run the offline regressions below. Copy the prepared installer directory to a
   Windows-native build path, preserving bytes. Run `build.ps1` with Windows
   PowerShell and the .NET Framework x64 compiler. `-OutputDirectory` and
   `-OutputName` are unchanged; use a private output directory for validation.
  Default output is `Dify-Setup-1.17.1-Windows-x64-1.0.10.exe` plus `.sha256` in
   Downloads, with refusal to overwrite an existing versioned EXE.
5. Run `tests/test_windows_bridge.ps1 -ExecutablePath <new-EXE-path>` on Windows.
   It extracts only to temporary directories; WSL preflight needs an existing
   WSL2/Docker runtime but does not install/start services. `-RunningDifyPort` is an
   optional explicit setup-API check, not an inference or clean-install test.

Preparation can download only the fixed public Git commit and Compose release;
it never downloads container images. Re-running it replaces generated upstream/API
copies and refreshes public plugin mirrors. `build.ps1` requires fresh receipts,
verifies their hashes and packs only an explicit file list, excluding stray `.env`
files, obsolete packages and local caches. Changing canonical source requires
preparing again. These receipts detect stale/corrupt build inputs, not publisher
signatures; the upstream pin and fixed binary hashes are the integrity boundary.

| Reviewed input | Required SHA-256 |
|---|---|
| AMDTokenFactory 0.0.10 package | `a52e0e67f0c152d2d458ac77e4ac4fc189bd69e2d29d81f07b3f2d3555ebb528` |
| Official Compose v5.6.0 Linux x86_64 | `40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a` |

The package digest is shared by preparation, the EXE self-test, runtime, tests and
notices. Fixed hash comparisons remain required; do not bypass guards, derive trust
from a mutable receipt or dynamically accept any package. Generated API and plugin
document copies are refreshed from canonical source during preparation, not edited.

Package-content/ZIP timestamp changes, including documentation edits, may produce a
different hash. Audit the new package and update **all** release hash references
together before releasing; do not bypass guards or reuse previous build evidence.

## Clean-checkout offline regressions

Provision the provider's locked dev environment and reviewed package/Compose plus
the pinned public Git object **before** disconnecting the build machine. In a
clean checkout, complete step 3 above, then run
`uv run --project plugins/amdtokenfactory --locked --no-sync pytest windows-installer/tests/test_installer.py`.
`pytest` and PyYAML come from that existing dev environment; no Dify backend
environment, Docker daemon or root backend integration tests are required.
The tests fail clearly when generated inputs have not been prepared. Compose
`config` parses only private temporary synthetic `.env` fixtures; test runs do not
read an installed `.env`, use saved keys, pull images or start containers.

Also syntax-check `prepare_payload.sh`, `payload/windows/runtime.sh` and
`payload/windows/prepare-remote-models.sh` with `bash -n`. API overlay regressions
and provider unit tests are separate focused suites, not a reason to run the
unrelated root Dify backend tests. No source-only result proves EXE compilation,
WSL clean installation, Marketplace approval or successful Chat/Agent/Workflow.

## API compatibility and deployment boundary

Supported baseline: Dify **1.17.1** at the pinned release commit, Plugin SDK
**0.10.2** and the reviewed daemon **0.6.10** family. The documented
`fetch-from-remote` flow is not connected end to end on that baseline; plugin upload
alone does not give an unmodified Dify Cloud native dynamic listing.

Two methods are overlaid:

- `ProviderConfiguration.get_provider_models`: uses native saved-credential policy
  checks to build a request-specific catalog while retaining model status/settings.
- `PluginModelRuntime.get_model_schema`: resolves the selected remote schema rather
  than reusing the generic one-hour static schema cache.

`prepare_overlay.py` checks the following original public files, unique anchors and
generated Python syntax, refusing an unknown baseline rather than patching it:

| Original implementation | Expected SHA-256 |
|---|---|
| `core/entities/provider_configuration.py` | `c174ff3023cfe5c08ef85461fef8864c1ee57ae9c82771c82e7dcc44351d988a` |
| `core/plugin/impl/model_runtime.py` | `32810fdfbd5caafb25af8f4fd2e13aeb1c2b7a8ce1113616883f53ebd61607e8` |

The WSL helper runs the generator in `langgenius/dify-api:1.17.1`, with network
disabled, a read-only root, dropped capabilities, no-new-privileges and host UID/GID.
It loads only public source, not app configuration or credentials. Four generated
files are bound read-only into API, API WebSocket, Worker and Worker Beat. The
generator does not restart services; activating the overlay **does** recreate
those four processes. The `remote-models` runtime action is a deployment operation,
not a read-only test. PostgreSQL/Redis/Weaviate/plugin-daemon data is not migrated,
and their services are not restarted by that action. Frontend and daemon ABI stay
unchanged. A changed upstream image fails the baseline guards and needs review.

## Runtime and credentials

The new plugin identity is `amdtokenfactory/amdtokenfactory`, canonical provider
`amdtokenfactory/amdtokenfactory/amdtokenfactory`. It is distinct from the old
`amdgpucloud/amdgpucloud/amdgpucloud` namespace, not a same-ID credential-preserving
upgrade. The rename does **not** migrate old credentials, defaults or application
references. An installed old Dify instance and its old plugin **must not be
uninstalled** as part of this rename; its saved Key **must not be exported, copied
or pasted into the new identity**. Keep the old instance and credentials untouched.
Any new-identity credential configuration requires separate user authorization in
an isolated instance; the installer does not read or transfer old credentials.

There are no model YAMLs, fallback IDs or polling: catalog/schema share the public metadata parser, use a
maximum 30-second memory cache scoped to credentials/tenant/provider, and report
discovery failure rather than a static/stale list. OCR/non-chat entries are excluded;
unknown output limits and missing prices are not invented.

The generic plugin-management button only opens native `/integrations`; it does not
extract files, install plugins, save keys or relax signature policy. Signature
verification defaults to enabled. Only explicit user consent changes it for a newly
created isolated instance. Install/start/stop retain unrelated Docker projects and
existing private configuration; stopping never deletes volumes or unregisters WSL.

Saved-key installation/inference probes and local synchronization scripts are not
build or runtime dependencies and are not included in this source change. Provider
Live tests remain explicitly opt-in with dedicated credentials, not automatic CI.
Do not interpret offline/build tests as all-model business or Marketplace acceptance.

Existing Downloads and installed artifacts predate this source simplification;
their checksums and deployment evidence are unchanged, not evidence of a new build.