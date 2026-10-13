# Windows Dify installer source and build

Integration author: **Letian Kang** — **Letian.Kang@amd.com**.

This directory contains the complete Windows bootstrapper source for Dify
**1.17.1**, installer **1.0.8**, and provider **0.0.8**. It uses an existing
WSL2/Docker runtime and downloads container images on first installation. It is
not an offline Docker/WSL distribution or an official signed AMD/Dify release.

The plugin ID is `letian-kang/amdgpucloud`; its model-provider name is
`letian-kang/amdgpucloud/amdgpucloud`. The dotted spelling `letian.kang` is not
accepted by Dify's native identifier grammar. Git repository ownership and
Marketplace publisher account verification are separate from this local slug.

## Source layout

- `DifySetup.cs`: x64 .NET Framework 4.8 / WinForms installer and manager.
- `build.ps1`: validates payload hashes, embeds ZIP, then compiles the EXE.
- `payload/windows/runtime.sh`: isolated local deployment and safe start/stop.
- `payload/docker`: pinned upstream deployment assets from commit
  `8387590ace4a094de812b7847fc6a4c3a27cd52b`, with original notices.
- `prepare_payload.sh`: restores reviewed generated plugin and Compose inputs.
- `tests/test_installer.py`: offline configuration/safety regression using a
  temporary synthetic configuration, not a user's `.env`.
- `tests/test_windows_bridge.ps1`: native EXE, WSL and optional HTTP checks.
- `tests/verify_saved_key_runtime.py`: opt-in bounded native calls using only
   credentials already saved in Dify. Choose the old canonical provider explicitly
   when checking an installed 0.0.7 instance; this never migrates keys.

The provider source is in `../plugins/amdgpucloud`. Generated `.difypkg`, EXE,
Compose binary, environments and build caches are excluded from Git. The
licenses and pinned binary checksums remain tracked.

## Build from source

1. In the provider directory, use Python 3.12, `uv sync --locked --group dev`,
   run `uv run --locked pytest` and `uv run --locked ruff check .`.
2. With the Dify Plugin CLI and `uv` on PATH, create
   `AMDGPUCloud-0.0.8.difypkg` and run `scripts/check_package.py`.
3. Run `prepare_payload.sh /absolute/path/to/AMDGPUCloud-0.0.8.difypkg`
   from Linux/WSL. It validates the package and fetches the pinned Compose
   binary only when missing. A previously downloaded binary with the exact
   checksum can be placed under `payload/tools` first.
4. Copy the prepared directory to a Windows-native build path. Run `build.ps1`
   using Windows PowerShell and the .NET Framework x64 compiler. It outputs
   `Dify-Setup-1.17.1-Windows-x64-1.0.8.exe` and its `.sha256` to Downloads,
   refusing to overwrite an existing versioned file.
5. Run the Python installer regressions and the native Windows bridge checks.

Package ZIP timestamps can make byte-for-byte rebuilds differ. This release
deliberately requires the reviewed package SHA-256. If a rebuilt package differs,
audit its contents and update **all** package hash references together before
releasing it; do not bypass the checksum guard or relabel previous evidence.

## Runtime and migration boundaries

The generic plugin-management button only opens Dify's native `/integrations`
page. It does not extract files, install plugins, save keys or relax signature
policy. Windows and Linux instance configuration and unrelated Docker projects
are never taken over or deleted.

Publisher changes create a different plugin ID. Native installation does not
automatically migrate credentials, defaults or App/Workflow references.
Configure the replacement first and remove the old provider only after an
explicit dependency review. The operator `install` and public-file sync scripts
are **mutating operations** and must not be used as read-only tests.

The source publication and offline/build tests do not prove Marketplace
approval, valid user keys or successful Chat/Agent/Workflow inference.