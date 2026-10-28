# CNS Reverse Outfits — Outfit Colours 0.4.12

Source and build instructions for reviewing the **Outfit Colours Preparer 0.4.12** download on Nexus Mods. The tool prepares alternate colour versions of installed custom Stellar Blade CNS outfits and creates a separate installer. Original choices remain available.

This snapshot fixes scans, packaging and installation stopping on unreadable headers in unrelated installed containers. Such files are reported, their filename chunk reservations are retained, and generated packages remain strictly validated. Malformed CNS rows no longer hide later valid outfits. The process-only script-policy fix from 0.4.11 is retained. Earlier public source snapshots remain in repository history. It includes the complete C# sources of both custom executables, their icon, the shipped Python/PowerShell/Lua scripts, and the vendored serializer source with its licence. It excludes personal settings, logs, test outputs, game/outfit files and development history.

## For reviewers

- **[Build instructions](BUILDING.md)** — compile both EXEs on Windows; optionally assemble a runnable copy using the unchanged 0.4.12 download as the dependency/data bundle.
- **[Review guide](review/NEXUS-REVIEW.md)** — entry points, file access, installation behaviour and first-run network activity.
- **[Dependencies](THIRD-PARTY.md)** — upstream source links, pinned versions and licences.
- **[Source manifest](review/SourceManifest.json)** — source checksums and the SHA256 of the reviewed download.
- **[Verification results](review/VERIFICATION.md)** — what was checked and its limits.
- **[End-user instructions](app/Assets/README.md)** — instructions shipped in the original download.

The original release archive is `Outfit-Colours-Preparer-0.4.12.zip` (142,333,770 bytes), SHA256:

```text
941114b8ef844bb4f7fd5d5bca1349d70902c0c877cbf5ee06bbfff2e97ebce4
```

The source repository does not contain the large third-party runtimes or compiled game-format data. Both of our EXEs can be compiled without those files. See BUILDING.md for the distinction between compiling the application and assembling a runnable distribution.

## Permissions

Source is provided for inspection and personal builds. No general open-source licence is granted for original project code or artwork by publishing this repository. Reuse permissions remain those stated by the author on the mod page. Third-party components retain their own licences and notices. See [LICENSING.md](LICENSING.md).

Development was assisted by OpenAI Codex. The application icon was created using image generation and supplied for use in this project.
