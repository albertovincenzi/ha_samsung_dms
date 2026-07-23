# Security Policy

## Supported Versions

This is a custom Home Assistant integration for Samsung DMS2.5 HVAC controllers.
Only the latest released version receives security fixes.

| Version | Supported |
| ------- | --------- |
| latest  | ✅        |
| older   | ❌        |

## Reporting a Vulnerability

Please **do not** open a public issue for security problems.

Report vulnerabilities privately via GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" under the repository's **Security** tab).

Please include:

- A description of the issue and its impact.
- Steps to reproduce.
- Affected version(s).

You can expect an initial response within 7 days. Fixes for confirmed issues
are released as soon as practical.

## Scope & Handling Notes

This integration talks to a DMS controller **only over the local network** and
stores the controller credentials in Home Assistant's config entry storage.
It makes no outbound internet calls. When reporting, please note that
controller credentials and local IP addresses are sensitive — redact them from
any logs you attach.
