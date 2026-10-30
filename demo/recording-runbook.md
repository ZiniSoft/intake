# Public demo recording runbook

This runbook keeps the public walkthrough reproducible while preventing production data or broad credentials from entering the recording environment.

## Environment boundary

1. Export a clean public tree and run the demo only from that tree.
2. Use a dedicated Compose project name and dedicated volumes.
3. Bind the demo web and API services to localhost on ports that do not overlap the running installation.
4. Generate new database, Redis, storage, session, and bootstrap secrets for the demo stack.
5. Never copy the private installation's `.env`, `.env.github`, database, storage volume, browser profile, or screenshots.
6. Destroy the demo volumes after the release artifacts are accepted.

## GitHub credential

Create a fine-grained personal access token with access to only `ZiniSoft/intake-demo`.

Required repository permissions:

- Metadata: Read
- Issues: Read and write

Store the token only in the clean demo tree's ignored `.env.github` file:

```dotenv
GITHUB_TOKEN_INTAKE_DEMO=<fine-grained-token>
```

The project configuration must reference the variable name `GITHUB_TOKEN_INTAKE_DEMO`, never the token value. Only the integration worker loads `.env.github`. Revoke the token after the final Issue and video have been verified.

## Deterministic AI result

The recording harness creates the Intake through the visible UI, then writes the fictional normalized result through the authenticated review API. This avoids depending on a third-party model during a timed recording and prevents retries from changing the wording.

The result must match `storyboard.md` exactly:

- Title: `Monthly report export times out`
- Type: `BUG`
- Priority: `P1`
- Route: `GITHUB`
- Summary: a fictional description of the report export timing out after about 30 seconds

This harness step represents the same stored normalized result that the normal AI worker produces. The final video must not claim that a specific model or provider generated the text.

## Rehearsal and final take

### Rehearsal

1. Run the visible flow through review and the approval confirmation.
2. Stop before the action that queues the real GitHub sync.
3. Continue the remaining camera moves with a seeded fictional Issue response in the isolated database.
4. Repeat until timing, pointer movement, captions, and narration are stable.

### Final take

1. Reset the isolated stack and confirm that `ZiniSoft/intake-demo` has no unintended open Issues.
2. Load the fine-grained token into `.env.github` and recreate only the integration worker.
3. Record one complete take that creates one real Issue.
4. Verify the Issue title, body, hidden Intake marker, and link back from the Intake journey.
5. Stop the demo stack, remove the token file, and revoke the token.
6. Review the pixels, audio, captions, and media metadata before upload.

## Publication

- Upload the H.264 MP4 and English VTT file as GitHub Release assets.
- Upload the same MP4 to YouTube and import the VTT captions.
- Keep only the SVG lifecycle diagrams, poster image, storyboard, narration, captions, and regeneration scripts in Git history.
- Do not commit raw recordings, browser profiles, Compose volumes, tokens, or the final MP4.
