# setup claude code

## setup public key

ssh-id-copy root@192.186.1.1

## install playwright

pip install playwright
playwright install chromium

## install claude code 

npm install -g @anthropic-ai/claude-code@latest

## set z.ai api key

~/.claude/settings.json

```json
{
  "env": {
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-4.5-air",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.2[1m]",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.2[1m]",
    "ANTHROPIC_AUTH_TOKEN": "fe44bfc4d6cb43828488bdc111ea1c2e.1YK68sdaseM95zcq",
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  },
  "permissions": {
    "defaultMode": "bypassPermissions"
  },
  "skipDangerousModePermissionPrompt": true
}
```

## install claude plugin 
git config --global url."https://github.com/".insteadOf "git@github.com:"

```bash
claude plugin marketplace add forrestchang/andrej-karpathy-skills
claude plugin install andrej-karpathy-skills@karpathy-skills

claude plugin marketplace add DietrichGebert/ponytail
claude plugin install ponytail@ponytail

claude plugin marketplace add thedotmack/claude-mem
claude plugin install claude-mem

claude plugin marketplace add microsoft/Webwright
claude plugin install webwright@webwright

claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install playwright@claude-plugins-official
claude plugin install skill-creator@claude-plugins-official
claude plugin install github@claude-plugins-official
```

## 
```bash
echo "export IS_SANDBOX=1" >> ~/.bashrc
source ~/.bashrc
claude
```

## run with Sandbox flag
IS_SANDBOX=1 claude --dangerously-skip-permissions


