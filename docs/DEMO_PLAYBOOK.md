# Dockyard Demo Playbook

Use this playbook to record consistent product demos for docs and social posts.

## 1) 60-second terminal demo flow

Run from a git repository with at least one checkpoint target:

```bash
python3 -m dockyard save --no-prompt \
  --objective "Launch Dockyard demo" \
  --decisions "Use proof-first narrative" \
  --next-step "Publish demo clip" \
  --risks "Need concise messaging" \
  --command "python3 -m dockyard resume"

python3 -m dockyard harbor
python3 -m dockyard search launch
python3 -m dockyard resume
python3 -m dockyard resume --json
```

## 2) 30-second cut

Minimal flow:

```bash
python3 -m dockyard save --no-prompt ...
python3 -m dockyard search "<keyword>"
python3 -m dockyard resume
```

## 3) Voiceover structure

1. Problem: context switching tax.
2. Action: checkpoint context with `save`.
3. Recovery: discover with `harbor/search`.
4. Outcome: resume with clear next steps.
5. Safety: non-invasive by default.

## 4) Demo quality gate

Before publishing:

- [ ] all commands in the clip exit successfully
- [ ] no incorrect flag usage (e.g., unsupported command options)
- [ ] output text is readable at social-video resolution
- [ ] safety statement is included in caption or narration

## 5) Supporting artifacts

- transcript file (command + output)
- source command list used for recording
- matching post copy from `docs/LAUNCH_KIT_X.md`
