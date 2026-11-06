# Booster language image (`vyomi/booster-lang`)

Implements BOOSTER-CODESPACES-GITHUB-APP.md section 11.2. The browser (v86, 32-bit) only has git + python;
every other language lives in this 64-bit image, which runs in the booster Codespace.

Files: `docker/booster-lang/{Dockerfile,build.sh,versions.json,scripts/refresh_versions.py}`,
`tests/booster_lang/smoke.sh`.

## Pinned versions (versions.json, resolved 2026-11-06 from upstream sources)

| Language | Version | Source / verification |
|---|---|---|
| Python | 3.15.2 | official `python:3.15.2-slim-trixie` image, copied into `/usr/local` |
| Node (LTS) | 26.13.0 (npm 11.20.0) | nodejs.org tarball, SHA256 from SHASUMS256.txt. No stable "Current" newer than LTS exists today (v27 is alpha) |
| Java | Temurin 25.0.5+8 (LTS, default) and 27.0.1.0.2+1 (latest) | Adoptium tarballs, SHA256 from API; `/opt/java/{lts,latest,current}` |
| Go | 1.27.3 | go.dev tarball, SHA256 from go.dev/dl json |
| Rust | 1.99.1 (cargo 1.99.1) | static.rust-lang.org installer, SHA256 from channel manifest; rustc+cargo+std only |
| .NET SDK | 10.0.403 (LTS; 11.0 is RC so excluded) | Microsoft tarball, SHA512 from releases.json |
| Ruby | 4.0.9 | official `ruby:4.0.9-slim-trixie` image |
| PHP | 8.5.12 | official `php:8.5.12-cli-trixie` image |
| C/C++ | gcc 14 / clang 19 (Debian trixie apt), cmake, make | smoke asserts major |
| Package managers | pip 26.3, npm 11.20.0, pnpm 12.18.0, yarn 1.22.22 (classic), Maven 3.10.0, Gradle 9.8.2, cargo, go mod, NuGet (in SDK), gem/bundler (in Ruby), Composer 2.11.1, apt | tarballs SHA-checked; Composer hashed at refresh time (no upstream checksum) |

Python/Ruby/PHP come from the docker-library images (same Debian trixie base, multi-arch, built from source by
them) instead of re-compiling here; pinned by exact tag, not by digest yet (Phase 2 signing should pin digests).

## Refresh
`python3 docker/booster-lang/scripts/refresh_versions.py` rewrites versions.json (`--check` only diffs).
It exits non-zero and writes nothing if any version or checksum cannot be resolved. Run it from the scheduled
job, then `build.sh`, then the smoke; promote only if green.

## Build / test
```
docker/booster-lang/build.sh [tag]          # native arch; release: buildx --platform linux/amd64,linux/arm64 --push
tests/booster_lang/smoke.sh [tag]           # per language: version == pin, hello build+run, package install, HTTP server + curl
```
Non-root user `booster` (uid 1000), workdir `/work`. Layer order is rarely-changing first (OS+C/C++, JDKs,
.NET, Go, Rust, Node/Maven/Gradle, then the copied images, then package-manager pins), so a version bump of a
late layer re-pulls only the layers at/after it.

## Size budget
Measured native arm64 build: 4.83 GB on disk; `docker save | gzip -1` is 1.26 GB (registry-compressed pull will be about that or a bit less). Big items: .NET SDK, two JDKs, Rust, clang+gcc. Levers if the
pull on `basicLinux32gb` is too slow: drop the second JDK (-0.3 GB), split into a core image + per-language
tags (`booster-lang:java`, `:dotnet`, ...) sharing the base layer. Not done yet; measure pull time on a real
Codespace before deciding. arm64 only was built and smoked here; amd64 (what Codespaces run) is built from the
same Dockerfile with amd64 checksums but is **unbuilt/untested** locally.

## Booster compose reference (snippet only; do not paste into the booster compose until the owner of that file agrees)
```yaml
  booster-lang:
    image: ${VYOMI_BOOSTER_LANG_IMAGE:-vyomi/booster-lang:dev}
    profiles: ["lang"]            # opt-in: docker compose --profile lang up -d
    command: ["sleep", "infinity"]
    working_dir: /work
    volumes:
      - booster-work:/work
    ports: ["8100-8199:8100-8199"]  # app ports exposed through the tunnel
    deploy: { resources: { limits: { cpus: "1.5", memory: 5g } } }   # leave headroom on 2 core / 8 GB
volumes:
  booster-work: {}
```
Run code: `docker compose exec booster-lang bash -lc 'cd /work && git clone ... && ...'`.

## How instances (EC2/GCE/VM compute via Docker) get a toolchain
Instances are `vyomi/instance:*` sshd containers created by `DockerComputeBackend` (`core/compute/backend.py`,
image from `VYOMI_INSTANCE_IMAGE` or per-instance AMI). Three options, in order of preference:
1. **Derived instance image (recommended):** `FROM vyomi/booster-lang` + sshd + the instance entrypoint, tagged as an AMI
   (e.g. `vyomi/instance:booster-lang`). Users pick it as the AMI/image; SSH + `git clone` + compile + run works with
   every language preinstalled. Zero runtime download.
2. **Shared toolchain volume:** populate a named volume from the image (`docker run --rm -v bl:/o vyomi/booster-lang
   cp -a /opt /o`) and mount it read-only at `/opt` in instances plus the PATH from the Dockerfile ENV line. Saves
   disk when many instances run; needs the same glibc (Debian trixie vs Ubuntu 24.04 is fine for these static-ish
   toolchains, but unverified).
3. **Inner Docker:** instances are privileged DinD-capable; `docker run vyomi/booster-lang` inside the instance works
   but pulls the image per instance store.
None of the three is wired into the backend yet (that file belongs to another workstream); only the image is built.
