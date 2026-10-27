# LoL Match Tracker → Discord

Posts a card to a Discord channel every time a tracked player finishes a League of Legends game.
It runs for free on **GitHub Actions** every 10 minutes: no bot, no server, your PC can stay off.

- Track any number of players by Riot ID (`Name#TAG`)
- Filter by queue (SoloQ, Flex…)
- Choose what gets posted: wins, losses or both
- One card style for wins and one for losses: champion splash art, icon, K/D/A, position, items, CS, damage, gold, vision and kill participation
- Optional random memes: static images are embedded in the card, GIFs are attached next to it
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
   > A private Discord webhook for a small group of friends. Every 10 minutes it checks the latest ranked matches of a handful of players (Account-V1 + Match-V5) and posts a summary image of each new game to our server. Not public, no data stored besides the last match IDs.
4. Personal keys don't expire. Once approved, replace the secret (step 4).

### 3. GitHub: create the repository
1. Create a free account at <https://github.com> if you don't have one.
2. **New repository** → name it (e.g. `lol-tracker`) → choose **Public** (unlimited free Actions minutes; your keys stay hidden in secrets) → **Create**.
3. **Add file → Upload files** and drag in everything from this folder, including the `.github` folder.
   - If the `.github` folder doesn't upload (some systems hide folders starting with a dot): **Add file → Create new file**, type the name `.github/workflows/tracker.yml` and paste the contents of that file.

> **Private repo?** It also works, but private repos get 2,000 free minutes a month. Change the schedule in `.github/workflows/tracker.yml` to every 30 minutes: `cron: "4-59/30 * * * *"`.

### 4. GitHub: add the secrets
Repository → **Settings → Secrets and variables → Actions → New repository secret**, twice:

| Name | Value |
|---|---|
| `RIOT_API_KEY` | your Riot key (`RGAPI-…`) |
| `DISCORD_WEBHOOK_URL` | the webhook URL from step 1 |

### 5. Choose the players
Edit `config.yaml` (click it on GitHub → ✏️ pencil → **Commit changes**):

```yaml
players:
  - name: "MyFriend"
    tag: "EUW"
  - name: "OtherFriend"
    tag: "1234"
```

### 6. First run
1. Repository → **Actions** tab → enable workflows if asked.
2. **LoL tracker → Run workflow**. The first run **only registers** the players (their previous games are not posted, to avoid flooding the channel).
3. Want to see a card right now? **Run workflow** again and type a Riot ID in *“post this player's latest match”*.

From then on it runs on its own every ~10 minutes.

---

## Configuration (`config.yaml`)

| Option | Values | What it does |
|---|---|---|
| `players` | list of `name` / `tag` / optional `region` | Who to track |
| `default_region` | `euw`, `eune`, `na`, `kr`… | Region when a player has none |
| `queues` | `soloq`, `flex` (also `normal`, `quickplay`, `aram`) | Which queues to watch |
| `show` | `wins` / `losses` / `both` | Which results get posted |
| `skip_remakes` | `true` / `false` | Ignore remakes |
| `language` | `es` / `en` | Card language |
| `timezone` | e.g. `Europe/Madrid` | Time shown on the card |
| `messages` | lists of texts | Message posted with the card; one is picked at random. Variables: `{player}` `{queue}` `{champion}` `{kda}` `{position}` `{duration}` |

## Memes
Put images in `memes/win/` and `memes/loss/` (upload them on GitHub with **Add file → Upload files** inside each folder).

- **PNG / JPG / WEBP** → embedded in the card, top-right.
- **GIF** → sent as a separate attachment in the same message (max 10 MB).
- One is picked at random each time. Empty folder = no meme.

## Testing on your PC (optional)
Requires Python 3.10+.

```bash
pip install -r requirements.txt
python -m tracker --demo          # renders sample cards into output/ (no keys needed)
```

To test with real data, create a `.env` file next to `config.yaml` (it's ignored by git):

```
RIOT_API_KEY=RGAPI-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

```bash
python -m tracker --test "Name#TAG" --dry-run   # renders that player's latest match into output/
python -m tracker --test "Name#TAG"             # posts it to Discord
python -m tracker --dry-run                     # full check without posting
```

## Good to know
- **Timing:** GitHub runs scheduled jobs "best effort", so posts can arrive a few minutes after the game ends.
- **Inactivity:** GitHub pauses scheduled workflows in repositories with no activity for 60 days. Every posted game updates `state.json`, which counts as activity; if nobody plays for two months, just re-enable it in the **Actions** tab.
- **Expired key:** if the run fails with *"Riot rejected the API key"*, your development key expired. Generate a new one or use a personal key.
- **Duo games:** if two tracked players are in the same game, each gets their own card.
- `state.json` stores the IDs of the matches already processed. Don't edit it; delete it to start over.

## Project structure
```
config.yaml                 settings (edit this)
memes/win, memes/loss       your memes
tracker/                    code
  __main__.py               entry point and main logic
  riot.py                   Riot API + Data Dragon clients
  match.py                  match data extraction
  card.py                   card rendering (Pillow)
  i18n.py                   card texts (es / en)
  memes.py, webhook.py      meme picking, Discord posting
fonts/                      Bebas Neue and Poppins (SIL Open Font License)
.github/workflows/          GitHub Actions schedule
```

---

LoL Match Tracker isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
