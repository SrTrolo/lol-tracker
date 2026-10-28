# LoL Match Tracker → Discord

Posts a card to a Discord channel every time a tracked player finishes a League of Legends game.
It runs for free on **GitHub Actions** every 5 minutes: no bot, no server, your PC can stay off.

- Track any number of players by Riot ID (`Name#TAG`), listed in a private repo so nobody can see who you track
- Filter by queue (SoloQ, Flex…)
- Choose what gets posted: wins, losses or both
- Defaults for everyone, and per-player queues, results and message texts when you want them
- One card style for wins and one for losses: champion splash art, icon, K/D/A, position, summoner spells, items (with the trinket and the role quest slot), CS, damage, gold, vision and kill participation
- Ranked games (SoloQ / Flex) also show the player's current rank: emblem, tier, division and LP
- Optional random meme inside the card; animated memes (GIF / WEBP) turn the card into an animated GIF
- Remakes are skipped

---

## Setup (about 15 minutes)

### 1. Discord: create a webhook
1. In your server, hover the channel → ⚙️ **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**.
2. Give it a name and avatar (that's what will show up as the author of the posts).
3. **Copy Webhook URL**. Treat it like a password.

### 2. Riot: get an API key
1. Sign in at <https://developer.riotgames.com> with your Riot account.
2. Your dashboard shows a **Development API Key**. It works right away but **expires every 24 h**, so it's only good for testing.
3. For permanent use, **register a Personal API Key** (Register Product → Personal API Key). Describe the project, e.g.:
   > A private Discord webhook for a small group of friends. Every 5 minutes it checks the latest ranked matches of a handful of players (Account-V1 + Match-V5) and posts a summary image of each new game to our server. Not public, no data stored besides the last match IDs.
4. Personal keys don't expire. Once approved, replace the secret (step 4).

### 3. GitHub: create the repository
1. Create a free account at <https://github.com> if you don't have one.
2. **New repository** → name it (e.g. `lol-tracker`) → choose **Public** (unlimited free Actions minutes; your keys stay hidden in secrets and the players in a private repo) → **Create**.
3. **Add file → Upload files** and drag in everything from this folder, including the `.github` folder.
   - If the `.github` folder doesn't upload (some systems hide folders starting with a dot): **Add file → Create new file**, type the name `.github/workflows/tracker.yml` and paste the contents of that file.

> **Private repo?** It also works, but private repos get 2,000 free minutes a month. Change the schedule in `.github/workflows/tracker.yml` to every 30 minutes: `cron: "4-59/30 * * * *"`.

### 4. GitHub: add the secrets
Repository → **Settings → Secrets and variables → Actions → New repository secret**, three times:

| Name | Value |
|---|---|
| `RIOT_API_KEY` | your Riot key (`RGAPI-…`) |
| `DISCORD_WEBHOOK_URL` | the webhook URL from step 1 |
| `STATE_KEY` | any long random text, e.g. the output of `python -c "import secrets; print(secrets.token_hex(32))"`. It keeps `state.json` from revealing who you track. If you change it, every player is registered again from scratch |

### 5. Choose the players
Create the private repo with your `players.yaml` and, if you want, your memes: see [Private repo](#private-repo-players-and-memes).

### 6. First run
1. Repository → **Actions** tab → enable workflows if asked.
2. **LoL tracker → Run workflow**. The first run **only registers** the players (their previous games are not posted, to avoid flooding the channel).
3. Want to see a card right now? **Run workflow** again and type a player's number (1 = the first in `players.yaml`) in *“post this player's latest match”*.

From then on it runs on its own every ~5 minutes.

---

## Configuration (`config.yaml`)
The settings for everyone. `default_region`, `queues`, `show`, `skip_remakes` and `messages` are defaults: each player can set their own in [`players.yaml`](#playersyaml).

| Option | Values | What it does |
|---|---|---|
| `default_region` | `euw`, `eune`, `na`, `kr`… | Region when a player has none |
| `queues` | `soloq`, `flex` (also `normal`, `quickplay`, `aram`, `mayhem` = ARAM: Mayhem) | Which queues to watch |
| `show` | `wins` / `losses` / `both` | Which results get posted |
| `skip_remakes` | `true` / `false` | Ignore remakes |
| `language` | `es` / `en` | Card language |
| `timezone` | e.g. `Europe/Madrid` | Time shown on the card |
| `messages` | lists of texts | Message posted with the card; one is picked at random. Variables: `{player}` (`Name#TAG`) `{name}` (just the name) `{queue}` `{champion}` `{kda}` `{position}` `{duration}` |
| `mentions` | `roles` / `users`: lists of Discord IDs | Pinged with every card; nobody else gets notified (see [Notifications](#notifications)) |

## Private repo (players and memes)
The players and the memes live in a separate **private** repository, so nobody who looks at or downloads this project can see who you track. The workflow fetches it on every run with a read-only deploy key.

1. Create a **private** repository (e.g. `lol-tracker-private`) with:
   ```
   players.yaml    who to track (see below)
   win/            memes for wins (optional)
   loss/           memes for losses (optional)
   ```
   **Add file → Create new file** for `players.yaml`; **Add file → Upload files** for the images.
2. Create a key pair on your PC: `ssh-keygen -t ed25519 -N "" -f private_repo_key`.
3. Private repo → **Settings → Deploy keys → Add deploy key**: paste the contents of `private_repo_key.pub` and leave *Allow write access* unchecked.
4. This repo → **Settings → Secrets and variables → Actions**:
   - Secret `PRIVATE_REPO_KEY`: the full contents of `private_repo_key` (the private key, `-----BEGIN` to `-----END`).
   - **Variables** tab → `PRIVATE_REPO`: `YourUser/lol-tracker-private`.
5. Delete both key files from your PC.

If the private repo can't be fetched, or it has no `players.yaml`, the run fails so you notice. Without `PRIVATE_REPO`, players are read from a `players:` list in `config.yaml` (which anyone can see) and cards are posted without memes.

### players.yaml
Edit it on GitHub like any file (✏️ pencil → **Commit changes**); changes apply on the next check. Only `name` and `tag` (the Riot ID, `Name#TAG`) are required, and anything a player leaves out comes from `config.yaml`:

```yaml
players:
  - name: "MyFriend"
    tag: "EUW"                  # everything from config.yaml

  - name: "OtherFriend"
    tag: "1234"
    queues: [soloq]             # only their SoloQ games
    show: losses                # only their losses
    messages:
      loss:                     # their own texts for losses; wins use config.yaml's
        - "💀 **{player}** strikes again with {champion} ({kda})"
```

| Setting | Values | When left out |
|---|---|---|
| `region` | `euw`, `eune`, `na`, `kr`… | `default_region` |
| `queues` | `soloq`, `flex`, `normal`, `quickplay`, `aram`, `mayhem` (ARAM: Mayhem) | `queues` |
| `show` | `wins` / `losses` / `both` | `show` |
| `skip_remakes` | `true` / `false` | `skip_remakes` |
| `messages` | `win` and/or `loss`, each a list of texts | the `config.yaml` texts, for wins and losses separately |

- Players are numbered in the order of the list (player 1, player 2…). That's how the public logs refer to them, and the number you type to test one.
- A misspelt setting stops the run with an error that names the player and the setting.

### Memes
- **PNG / JPG / WEBP / GIF**. The meme sits in a square frame next to the title, cropped to fit, so a centred subject works best.
- With an animated GIF or WEBP the whole card is posted as an animated GIF. GIFs only have 256 colours, so its background looks slightly grainier than the usual PNG. If it would go over Discord's 10 MB limit, the card is sent still.
- One is picked at random each time. Empty or missing folder = no meme, and no frame on the card.

## Privacy
This repo is public: anyone can see the code, `config.yaml`, `state.json` and the Actions logs. None of them say who you track:
- The players and their settings are only in the private repo.
- `state.json` only holds codes made with `STATE_KEY`, not Riot IDs or match IDs.
- The logs say "player 1", "player 2"… instead of names, and the test input takes that number.

What can still be worked out: how many players are tracked (the entries in `state.json`) and when their games end (the times of the "Update tracker state" commits). The Discord channel shows the names, of course.

## Notifications
Posts don't ping anyone unless you list them in `mentions`. To notify only some people:
1. Create a role (e.g. `@LoL`), turn on **Allow anyone to @mention this role** and give it to whoever wants the notifications.
2. Enable **Developer Mode** (User Settings → Advanced), right-click the role → **Copy Role ID** and add it to `config.yaml`:
   ```yaml
   mentions:
     roles: ["123456789012345678"]
   ```
3. In the server settings, set the default notifications to **Only @mentions**, so the rest of the server isn't notified of every post.

## Testing on your PC (optional)
Requires Python 3.10+.

```bash
pip install -r requirements.txt
python -m tracker --demo          # renders sample cards into output/ (no keys needed)
```

To test with real data, clone your private repo into `private/` (it's ignored by git), so the tracker finds the players and memes: `git clone <private repo URL> private`. Then create a `.env` file next to `config.yaml` (also ignored by git). `STATE_KEY` must be the same as the secret, and is only needed for a check that isn't a `--dry-run`:

```
RIOT_API_KEY=RGAPI-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
STATE_KEY=...
```

```bash
python -m tracker --test 1 --dry-run            # renders player 1's latest match into output/
python -m tracker --test "Name#TAG" --dry-run   # same, for any Riot ID
python -m tracker --test 1                      # posts it to Discord
python -m tracker --dry-run                     # full check without posting
```

## Good to know
- **Timing:** GitHub runs scheduled jobs "best effort", so posts can arrive a few minutes after the game ends.
- **Inactivity:** GitHub pauses scheduled workflows in repositories with no activity for 60 days. Every posted game updates `state.json`, which counts as activity; if nobody plays for two months, just re-enable it in the **Actions** tab.
- **Expired key:** if the run fails with *"Riot rejected the API key"*, your development key expired. Generate a new one or use a personal key.
- **Duo games:** if two tracked players are in the same game, each gets their own card.
- **Rank:** it's read when the card is posted, so it shows the LP right after the game. Rank emblems come from [CommunityDragon](https://communitydragon.org) (the League client's own images); if they can't be downloaded, the tier and LP are shown without the emblem.
- `state.json` stores the matches already processed, as codes made with `STATE_KEY`. Don't edit it; delete it to start over.

## Project structure
```
config.yaml                 settings for everyone (edit this)
private/                    your private repo, cloned here for local runs (ignored by git)
tracker/                    code
  __main__.py               entry point and main logic
  riot.py                   Riot API + Data Dragon clients
  match.py                  match data extraction
  card.py                   card rendering (Pillow)
  gif.py                    animated card encoding
  i18n.py                   card texts (es / en)
  memes.py, webhook.py      meme loading, Discord posting
fonts/                      Bebas Neue and Poppins (SIL Open Font License)
.github/workflows/          GitHub Actions schedule
```

---

LoL Match Tracker isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
