# CNS Reverse Outfits â€” Outfit Colours 0.4.11

Source and build instructions for reviewing the **Outfit Colours Preparer 0.4.11** download on Nexus Mods. The tool prepares alternate colour versions of installed custom Stellar Blade CNS outfits and creates a separate installer. Original choices remain available.

This snapshot includes the 0.4.11 fix for unsigned extractor scripts being blocked by a local PowerShell execution policy. The policy is applied only to the extractor subprocess; saved Windows policies are unchanged and administrator-enforced policies remain respected. The earlier 0.4.10 source remains available in repository history. It includes the complete C# sources of both custom executables, their icon, the shipped Python/PowerShell/Lua scripts, and the vendored serializer source with its licence. It excludes personal settings, logs, test outputs, game/outfit files and development history.

## For reviewers

- **[Build instructions](BUILDING.md)** â€” compile both EXEs on Windows; optionally assemble a runnable copy using the unchanged 0.4.11 download as the dependency/data bundle.
- **[Review guide](review/NEXUS-REVIEW.md)** â€” entry points, file access, installation behaviour and first-run network activity.
- **[Dependencies](THIRD-PARTY.md)** â€” upstream source links, pinned versions and licences.
- **[Source manifest](review/SourceManifest.json)** â€” source checksums and the SHA256 of the reviewed download.
- **[Verification results](review/VERIFICATION.md)** â€” what was checked and its limits.
- **[End-user instructions](app/Assets/README.md)** â€” instructions shipped in the original download.

The original release archive is `Outfit-Colours-Preparer-0.4.11.zip` (142,332,637 bytes), SHA256:

```text
66e36b9468a839db3a8d4ec9f243b24cd1020ba62cb6d1ee6559224cf0c29e62
```

The source repository does not contain the large third-party runtimes or compiled game-format data. Both of our EXEs can be compiled without those files. See BUILDING.md for the distinction between compiling the application and assembling a runnable distribution.

## Permissions

Source is provided for inspection and personal builds. No general open-source licence is granted for original project code or artwork by publishing this repository. Reuse permissions remain those stated by the author on the mod page. Third-party components retain their own licences and notices. See [LICENSING.md](LICENSING.md).

Development was assisted by OpenAI Codex. The application icon was created using image generation and supplied for use in this project.
