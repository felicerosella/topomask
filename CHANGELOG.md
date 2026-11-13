# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project logo with a dark-theme variant, application icon and favicon.

## [0.1.0] - 2026-11-13

### Added

- Single-file web app (`topomask.html`) with a strict Content Security Policy and no network access.
- Reversible, topology-preserving anonymization of IPv4/IPv6 addresses, domains, hostnames, users, email addresses, MAC addresses, GUIDs, SIDs, LDAP DNs, UNC paths, shell prompts, `/etc/hosts` lines and syslog headers.
- Irreversible removal of secrets: private keys, bearer tokens, JWTs, cloud API keys, passwords in key/value pairs, URLs and XML, Cisco secrets, SNMP communities, pre-shared keys, password hashes, SSH fingerprints and payment cards.
- Checksum-validated Italian personal data: IBAN, tax code, VAT number; phone numbers.
- User-defined terms, keep list, per-category settings and a mapping browser.
- English and Italian interface.
- Windows desktop app with notification-area icon, global hotkeys (Ctrl+Alt+A, Ctrl+Alt+R) and clipboard history exclusion for restored text.
- Release artifacts with SHA-256 checksums, CycloneDX SBOM and build provenance attestation.

[Unreleased]: https://github.com/felicerosella/topomask/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/felicerosella/topomask/releases/tag/v0.1.0
