# Evaluator-only material

Files below this directory are human evaluation inputs. They are not loaded into
Agent prompts and are outside target-repository tool scopes. Keep them separate
from benchmark source repositories to avoid leaking expected classifications.

For Mini Raft, `project.yaml` contains verifier-only checks and fixture mappings;
`hidden-acceptance/` is copied into a patched worktree only after Agent 3 returns,
then removed after deterministic verification. Agents receive a sanitized project
view without those fields.
