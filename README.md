# sehosun

A Claude Code plugin marketplace by Seho Sun (CAMP Lab, Yeungnam University) — academic paper automation, computational chemistry, and remote-machine setup.

## Install

Add the marketplace once:

```
/plugin marketplace add SHSUN76/sehosun
```

Then install any plugin from it:

```
/plugin install <name>@sehosun
```

For example, `/plugin install tailscale-ssh@sehosun`.

> **Add this marketplace as a git source, not as a raw file URL.**
> `/plugin marketplace add SHSUN76/sehosun` clones the repository, which is what lets
> Claude Code resolve plugin sources relative to the repository root. Adding the
> marketplace by a raw URL to `.claude-plugin/marketplace.json` gives Claude Code a
> bare JSON document with no repository behind it, so any relative-path plugin added
> here in future will fail to resolve.

## Plugins

| Plugin | What it does | Access |
| --- | --- | --- |
| `compchem` | DFT / MD / MLIP workflow router for Quantum ESPRESSO, LAMMPS, OpenMM, MACE and CHGNet, with a Socratic calculation planner, input validator, and safe restart protocol. | Private |
| `paper-autopilot` | Multi-corpus (MoE) academic paper pipeline: scaffold, forcing-question gates, experimental SOP design, figure mockup evolution, corpus-routed drafting, adversarial spec review. | Private |
| `paper-autopilot-open` | Public standalone edition of the paper pipeline, with guided onboarding and dual local/Supabase RAG. Ships disabled by default. | Public |
| `tailscale-ssh` | Establish SSH between two machines with no VPN, no port forwarding, and no inbound firewall rule, over a Tailscale WireGuard tunnel. | Public |

Plugins marked **Private** live in private repositories and resolve only for GitHub
accounts that have read access to them — in practice, CAMP Lab members. Everyone else
sees them listed here but cannot install them; the public plugins are unaffected.

## The two Paper Autopilot editions are mutually exclusive

`paper-autopilot` (MoE edition) and `paper-autopilot-open` share 9 skill names, roughly
32 agent names, and the same `/paper-autopilot` command tree. Installing both puts two
definitions behind every one of those names, and which one answers is not something you
want to guess at mid-manuscript. Install exactly one.

`paper-autopilot-open` therefore carries `defaultEnabled: false`: installing it does not
switch it on. Enable it only after confirming the MoE edition is not installed.

## Roadmap

Phase 1 (this release) indexes four plugins that live in their own repositories. A later
phase bundles the locally developed skills into this repository:

- `research-writing`
- `origin-graphs`
- `hwp-surgery`
- `teaching-kit`
- `agent-workflow`

## License

MIT — see [LICENSE](LICENSE). Each referenced plugin carries its own license in its own
repository.
