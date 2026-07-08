# Privacy and Security

This repository is public-facing, so it is limited to code, templates, and documentation. The working setup touches participant communication and MRI-derived files, but the repository itself does not contain operational secrets or participant data.

## Not Tracked in Git

- Google OAuth files such as `credentials.json` and `token.json`
- SMTP usernames, passwords, app passwords, and `.env` files
- protected spreadsheet passwords and local paths to lookup files
- participant names, email addresses, phone numbers, and appointment exports
- DICOM, NIfTI, and other participant-derived MRI files
- generated MRI screenshot packages unless a file is synthetic or explicitly cleared for public release
- scheduler exports or batch files that include local usernames, machine paths, or private operational details

## Credential Handling

Google OAuth files are expected locally at `config/credentials.json` and `config/token.json`. Both paths are ignored by Git. SMTP values and protected spreadsheet lookup settings are read from environment variables, so passwords and private paths stay outside source code.

If a Google token expires or is revoked during scheduled execution, the script can notify a maintainer through `STUDY_REAUTH_NOTIFY_EMAIL`. This stays in an environment variable rather than a hard-coded personal address.

## MRI Examples

No real MRI example is included in this repository. A structural scan can still be privacy-sensitive even when obvious identifiers are removed. A public example should only be added if it is synthetic, heavily derived, or sourced from a public dataset with clear license and attribution.

## Repository Cleanup

Earlier versions of the standalone reminder repository included placeholder credential/token files. They are now removed from the working tree and ignored. No real credentials were ever committed.
