<!-- SPDX-FileCopyrightText: 2026 Julien Malka -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Contributing

Contributions are welcome: issues, fixes and pull requests.

## Licences

Each file says which licence it is under, in its header or in `REUSE.toml`, and
`reuse lint` checks that every file does. In short:

| Part | Licence |
|---|---|
| The app (`Hermes*/`, `Shared/`) | AGPL-3.0-or-later, with the additional terms in `TRADEMARKS.md` |
| The relay (`relay/`) | AGPL-3.0-or-later |
| The plugin and the native code (`plugin/`, `native/`), the twin's tests | MIT |
| Documentation | CC-BY-4.0 |
| Calibration and test data | CC0-1.0 |
| The name and the icon | reserved |

A new file carries the header of the part it belongs to (`reuse annotate`).

## The contributor agreement

The app is distributed through Apple's App Store, whose terms the GPL family of
licences does not accommodate. To be able to ship your contribution there, its
author needs more than the AGPL gives. So before a first pull request is
merged, you sign the contributor agreement in `CLA.md`: a bot asks you to on
that pull request, and one signature covers everything you contribute
afterwards. It does not take your copyright: you keep it, and may license your
contribution to anyone else as you wish.

## Checking a change

`README.md` lists the commands that check each part.
