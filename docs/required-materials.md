# Materials required for live ConsensusSeam runs

## Required for the first DeepSeek integration run

1. A funded or otherwise usable DeepSeek API key. Export it as
   `DEEPSEEK_API_KEY`; do not paste it into `project.yaml` or commit it.
2. Network access to `https://api.deepseek.com`. If the environment uses a
   compatible gateway, provide its URL through `DEEPSEEK_BASE_URL`.
3. Authorization to send requested source snippets and tool results to DeepSeek.
   This is especially important for private or confidential target repositories.
4. A local Go target at a known committed Git revision. Worktrees start from
   `HEAD`; unrelated dirty working-tree changes are intentionally not copied.
5. A target manifest containing the repository path, working directory, build and
   test commands, the intended `system_boundary`, and deterministic capability
   checks for every capability Agent 2 may implement.

## Required for a non-Raft target

- A short protocol brief under `spec/protocols/<protocol>.yaml`: roles, message
  families, timing/randomness sources, persistent concepts, observation examples,
  and existing external inputs. It describes concepts, not assumed function names.

## Required before the etcd-raft benchmark

- The exact etcd-raft repository/revision, or permission to clone a selected
  public revision.
- Confirmation that the boundary is the Raft protocol library rather than the
  complete etcd deployment.
- The build/test commands appropriate for that revision.
- Human-reviewed expected classifications for the initial analyze-only run. These
  are evaluation ground truth, not hints injected into the Agent prompt.

## Useful but optional experimental inputs

- A maximum API spend or token budget per run.
- The desired comparison profiles: `all-flash`, `all-pro`, and/or `mixed`.
- A second Go implementation with clearly poorer testability.
- Human labels for `SUPPORTED`, `PATCHABLE`, and `INVASIVE` capabilities and an
  agreed scoring rubric for classification and avoidable modifications.
