# Security Policy

## Supported versions

Only the latest release gets security fixes. ACEVIDS does not update itself,
so install new releases yourself.

| Version | Supported |
| ------- | --------- |
| 2.x     | Yes       |
| 1.x     | No        |

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/SaviourV2/acevids-editor/security/advisories/new),
not in public issues.

Include what you found, how to reproduce it, and the ACEVIDS version and OS.
You'll get a reply as soon as possible. Once a fix ships you'll be credited
in the advisory unless you'd rather not be.

## Verifying releases

Every release asset is listed in `SHA256SUMS.txt` and has a signed
build-provenance attestation:

```bash
gh attestation verify <file> --repo SaviourV2/acevids-editor
```
