# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-11-13

Version 0.2.0 was tagged but never published: its installer did not match the attested build. 0.2.1 contains all the 0.2.0 changes listed below plus these fixes.

### Security

- Bundled Pillow updated to 13.0.0, fixing the advisories published for 12.3.0 and earlier. topomask only loads its own icon, so it was not exposed to malicious images, but no release ships known-vulnerable components.

### Fixed

- Release pipeline: the published installer is the attested build; every release file is verified against its provenance attestation before publishing.
- The installer is always built with the pinned, checksum-verified Inno Setup, never with a version preinstalled on the build machine.

### Changed

- Building from source and the development tools now require Python 3.11 or later (the app bundles its own Python, so users are not affected).

## [0.2.0] - 2026-11-13 [not published]

### Added

- Profiles: separate mappings, terms and keep lists per customer or project, with a selector in the sidebar. Existing data moves into the `default` profile automatically. Hotkey notifications name the profile when there is more than one.
- Storage, cloud and hardware identifiers: Fibre Channel WWNs, SCSI NAA/EUI identifiers and multipath WWIDs (vendor part kept), iSCSI IQNs (domain mapped consistently), AWS ARNs and account IDs, serial numbers. New `infra` category in Settings.
- Configurable global shortcuts in the desktop app (Settings → Keyboard shortcuts), applied without restarting; a combination already used by another application keeps the previous one active.
- `topomask.html` is published as a release asset, with checksum and build attestation.

### Changed

- Data layout: settings stay at the root of the data folder, mappings, terms and keep lists move to `profiles/<name>/`. Migration from 0.1.0 is automatic and one-way: after upgrading, going back to 0.1.0 starts with an empty mapping.

## [0.1.0] - 2026-11-13

### Added

- Single-file web app (`topomask.html`) with a strict Content Security Policy and no network access.
- Reversible, topology-preserving anonymization of IPv4/IPv6 addresses, domains, hostnames, users, email addresses, MAC addresses, GUIDs, SIDs, LDAP DNs, UNC paths, shell prompts, `/etc/hosts` lines and syslog headers.
- Irreversible removal of secrets: private keys, bearer tokens, JWTs, cloud API keys, passwords in key/value pairs, URLs and XML, Cisco secrets, SNMP communities, pre-shared keys, password hashes, SSH fingerprints and payment cards.
- Removal of ASCII-art and framed login banners.
- Checksum-validated Italian personal data: IBAN, tax code, VAT number; phone numbers.
- User-defined terms, keep list, per-category settings and a mapping browser.
- English and Italian interface.
- Windows desktop app with notification-area icon, global hotkeys (Ctrl+Alt+A, Ctrl+Alt+R) and clipboard history exclusion for restored text.
- Per-user Windows installer with Start menu entry, optional sign-in autostart and uninstaller, plus a portable zip.
- Opt-in daily update check in the desktop app; nothing is downloaded automatically.
- `--tray` and `--debug` command-line options.
- Release artifacts with SHA-256 checksums, CycloneDX SBOM and build provenance attestation.

[Unreleased]: https://github.com/felicerosella/topomask/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/felicerosella/topomask/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/felicerosella/topomask/releases/tag/v0.1.0
