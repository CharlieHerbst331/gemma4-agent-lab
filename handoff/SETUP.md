# Setup on Charles's Mac (for Antigravity)

Everything here runs on the Mac. GPU work happens on Kaggle; nothing heavy runs locally.
Do not download the full competition dataset or the model onto the Mac.

## 1. Tools

```bash
# Homebrew (skip if `brew --version` works)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git gh uv          # uv also manages Python 3.12+ for the project
```

## 2. GitHub auth (Antigravity needs this to push branches and open PRs)

```bash
gh auth login                   # GitHub.com → HTTPS → "Login with a web browser"
gh auth setup-git               # lets plain `git push` use the gh credential
gh auth status                  # must show CharlieHerbst331 with repo scope
```

## 3. Clone and install

```bash
mkdir -p ~/code && cd ~/code
gh repo clone CharlieHerbst331/gemma4-agent-lab
cd gemma4-agent-lab
uv sync --locked                # creates .venv, installs gemma-lab and kaggle==2.2.4
make check                      # ruff + pytest; must pass
uv run gemma-lab --help
```

Open `~/code/gemma4-agent-lab` as the workspace folder in Antigravity. It loads `AGENTS.md`
and `.agents/rules/*.md` automatically and offers the skills in `.agents/skills/` as slash
commands (`/pack-agent`, `/push-dev13`, `/analyze-dev13`, `/submit-candidate`).

## 4. Kaggle CLI

The project pins `kaggle==2.2.4`, so `uv run kaggle …` works after `uv sync`. To also have a
global `kaggle` command (optional):

```bash
uv tool install "kaggle>=2.2.4"
```

The scripts default to `uv run kaggle`. Set `KAGGLE_BIN=kaggle` to use the global one.

## 5. Kaggle API token

1. Sign in at https://www.kaggle.com as `charlesaherbst` and open https://www.kaggle.com/settings
   → **API** section.
2. Pick one:
   - **Recommended: API token.** Click **Generate New Token** and copy the `KGAT_…` value. Save
     the raw token (no JSON, no quotes) to `~/.kaggle/access_token`:
     ```bash
     mkdir -p ~/.kaggle && chmod 700 ~/.kaggle
     pbpaste > ~/.kaggle/access_token     # after copying the token
     chmod 600 ~/.kaggle/access_token
     ```
   - **Legacy key file.** Under **Legacy API Credentials**, click **Create Legacy API Key**.
     It downloads `kaggle.json` (`{"username":"charlesaherbst","key":"<32 hex>"}`):
     ```bash
     mkdir -p ~/.kaggle && chmod 700 ~/.kaggle
     mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json
     chmod 600 ~/.kaggle/kaggle.json
     ```
3. The quirk: a `KGAT_` token does **not** work as the `key` in `kaggle.json` or in
   `KAGGLE_KEY`. If you put one there (the old box did), `. scripts/handoff/kaggle_env.sh` moves
   it to `KAGGLE_API_TOKEN` and unsets `KAGGLE_KEY`. Also remove any `KAGGLE_KEY` export from
   `~/.zshrc`.
4. The token stays in `~/.kaggle/`, outside the repo. `.gitignore` blocks `kaggle.json`,
   `access_token` and `credentials.json`; never copy them into the repo or paste them in chat.

## 6. Verify

```bash
cd ~/code/gemma4-agent-lab
. scripts/handoff/kaggle_env.sh
$KAGGLE_BIN competitions submissions gemma-4-developer-agent   # table; newest: 58037165, 0.17
$KAGGLE_BIN kernels list --mine --page-size 5                   # the dev-13 kernels
uv run gemma-lab doctor --online
scripts/handoff/pack.sh structured-v22                          # sha c45c6c4c…; matches PR #51
scripts/handoff/push_dev13.sh structured-v22 s0                 # DRY RUN only; builds a notebook
```

If the competition table prints, Kaggle access works. If you see "Found an API token
(KGAT_...) in …", you are hitting the quirk in step 5.3. If you see a 403 on the competition,
accept the competition rules in the browser (Charles must do this himself).

## 7. Box context (optional but recommended)

Extract the artifacts tarball outside the repo:

```bash
mkdir -p ~/gemma4-context
tar -xzf ~/Downloads/gemma4-handoff-artifacts.tar.gz -C ~/gemma4-context
open ~/gemma4-context/README.md
```

To use it in Antigravity, add `~/gemma4-context` as a second folder in the project (read-only
reference). Reproduce the v22 table:

```bash
C=~/gemma4-context/gemma4-team
uv run python scripts/handoff/analyze_dev13.py \
  v21-1-s1=$C/testing/v21-1-walltime/out v21-1-s3=$C/v22/out/paired-nb-v21-1-s3 \
  v22-s1=$C/v22/out/paired-nb-v22-s1 v22-s2=$C/v22/out/paired-nb-v22-s2 \
  v22-s3=$C/v22/out/paired-nb-v22-s3 bundle-s1=$C/v22/out/paired-nb \
  bundle-s2=$C/v22/out/paired-nb-bundle-s2 bundle-s3=$C/v22/out/paired-nb-bundle-s3
```
