# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

Only the latest release receives fixes.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: **Security → Report a vulnerability** on this repository ([private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)). Do not open a public issue.

Include the version, the mode (browser or Windows app), steps to reproduce and, if relevant, a minimal input made only of documentation values (`192.0.2.0/24`, `example.net`, `2001:db8::/32`). Never send real logs or real secrets.

You can expect an acknowledgement within 7 days. Fixes are released as a patch version and credited in the changelog unless you prefer otherwise.

## Threat model

topomask aims to keep sensitive values out of text that you send to a third party (typically an AI service), while letting you restore them locally.

In scope:

- Real values that should have been replaced but appear in the anonymized output (detection gaps, regressions).
- Secrets that are restorable or recoverable from the output.
- Any network access from `topomask.html` or the desktop app, any way to bypass the Content Security Policy.
- Script injection through processed text, terms or mapping data (the UI never uses `innerHTML` for user content).
- Restored values leaking into the Windows clipboard history or cloud clipboard, or into `topomask.log`.
- Supply-chain issues in the release artifacts.

Out of scope and documented as known limitations:

- `map.json` is stored in clear text in `%APPDATA%\topomask\` or in the browser's local storage. Anyone with access to your user profile can read the mapping. DPAPI encryption is planned for 1.0.
- The original text you copied remains in the clipboard history.
- Detection is heuristic: personal names in free text and data in unusual formats are not detected. Review the output before sharing it.
- A real value shaped like an already assigned fake is restored incorrectly.
