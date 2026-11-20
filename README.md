# FTN Blueprint Library

Community blueprint sharing for the game **Find The Needle**.

A Windows desktop app (Python + PySide6) that reads your local
`…\Godot\app_userdata\FindTheNeedle\blueprints\` folder, browses and downloads
community blueprints (installing them **safely** into the game folder), and
publishes your own. Browsing and downloading need no signup: players are
identified only by the game's own `install_key`. Uploading and rating need a
free account — created with nothing but a **name** (no password), because the key
itself is the credential.

> This repository contains the **desktop client and the shared
> parsing/preview library only** — the full source of everything that ships in
> the `.exe`. The hosted library service it talks to is not part of this repo.

---

## Highlights

- **Real parsing, not screenshots.** `.blueprint` files are Godot binary `Variant`
  blobs. They are decoded byte-exactly, so metadata (name, cost, piece count,
  building mix) and the isometric preview come from the actual placed pieces.
- **Safe installer.** Validates → sanitises the name → refuses while the game is
  running → backs up collisions → writes atomically → re-verifies. It only ever
  *adds* `.blueprint` files inside `blueprints/`; it never touches game saves.
- **One preview generator for both sides.** The shared code renders an SVG that
  the client rasterises with Qt, so what you see is what the library produced.
- **Anonymous by default, accountable where it matters.** Identity is the game's
  `install_key`, stored only as a salted hash — never the key itself, and never
  its hash either: the hash stays in a private column and is not returned by any
  API response, so it can never be lifted out of a public payload to impersonate
  its owner. Uploading and rating are the two actions that need a free account,
  and that account is bound one-to-one to the key, so a rating can never be cast
  twice and every upload is always traceable. A second registration from the same
  game install is refused and told to sign in to the existing account.
- **Passwordless by design.** Account creation asks for a name and nothing else:
  the game key *is* the credential. Sign-in needs no password — if the key is
  already on file the client signs you in automatically. Login tokens are stored
  only as their SHA-256 digest. No email address is ever collected, and there is
  no password to reset or mail server to run.
- **Portable accounts.** Because the key is generated per install, a wiped drive
  or a new PC would otherwise strand an account. Every account is issued a
  one-time **recovery code** at registration (shown once, stored only as a salted
  hash); entering it on a new install re-binds the account — keeping your name
  and uploads — and rotates the code.
- **Retail-only, format-checked.** All of this relies on the game's real
  `install_key`. The library accepts only a well-formed 64-character hex key, so a
  cracked build cannot register with a made-up string; such a build can still
  browse and download, but account creation, uploads and ratings are disabled
  with a message that the library works only with the retail version of the game.
  New registrations are additionally rate-limited per IP.

---

## Repository layout

```
shared/ftn_blueprint/      Godot Variant codec, blueprint parser, SVG preview   (stdlib only)
shared/tests/              codec + parser + preview tests and real fixtures
client/                    PySide6 desktop app
  app/core/                paths, identity, library scan, installer, API client, provenance
  app/ui/                  main window, 4 views, widgets (cards, preview canvas, account dialog, toasts…)
  app/themes/              base.qss + palettes.json (3 themes)
  tests/                   headless UI + core tests
```

---

## Quick start

```powershell
python -m pip install -r client/requirements.txt
python client/run.py
```

The client uses the production library server configured in
`client/app/config.py`. **Settings → Server** shows the endpoint and lets you
check whether it is online; the address is not user-editable.

If your blueprint folder is not auto-detected, point the client at it in
**Settings → Blueprints folder**.

To upload or rate a blueprint, sign in first — the account button at the bottom
of the left rail opens a small dialog where you create an account with just a
**name** (no password) or sign in. Sign-in is automatic whenever your game key is
already on file, so normally you never touch the dialog twice. Registration shows
a one-time **recovery code** — save it: it is the only way to move the account to
a new PC. The dialog's **Get recovery code** button issues a fresh one, and
**Use a recovery code** on a new install re-binds the account to it. If your game
install has no key (a pirated build), browsing and downloading still work, but
uploading and rating are disabled and the dialog explains that the library works
only with the retail version of the game.

---

## Configuration (client)

| Variable | Meaning |
| --- | --- |
| `FTNLIB_DATA_DIR` | Override `%LOCALAPPDATA%\FTNBlueprintLibrary` |
| `FTNLIB_GAME_DIR` | Override the detected Godot user-data directory |
| `FTNLIB_API_BASE_URL` | Point the client at a different server (mainly for local testing) |

The first two are mainly useful for tests and portable installs. The production
client uses the API address built into the app.

---

## Building the Windows executable

```powershell
python -m pip install pyinstaller
pyinstaller client/build/ftnlib.spec --noconfirm --workpath client/build/work --distpath client/dist
```

Output: `client/dist/FTNBlueprintLibrary/FTNBlueprintLibrary.exe` (one-dir,
windowed, icon + version resource). Ship the whole `FTNBlueprintLibrary` folder.

---

## Tests

```powershell
python -m pytest client/tests shared/tests -q     # codec, client core, headless UI
```

> UI tests run headless via `QT_QPA_PLATFORM=offscreen` and use temp dirs
> (`FTNLIB_DATA_DIR` / `FTNLIB_GAME_DIR`), so they never touch a real install.

---

## The `.blueprint` format

```
file    = [u32 LE payload_len][Godot binary Variant]
payload = DICTIONARY with exactly 19 keys:
          format, id, name, desc, icon, colour, category, sub, mk, made,
          rows, ids, costs, tags, pins, unplugged, feeds, paints, orders
```

- `format` = schema version (currently `1`); anything else is rejected with a
  clear error and never written to disk.
- `id` = `<unix_ts>_<4hex>`; `made` = the unix timestamp (matches the filename).
- `rows[]` = one dictionary per placed structure; `ids[]` the matching building
  ids; `costs[]` the per-piece build cost.
- Values are little-endian; each value is prefixed by a `u32` type id
  (with a flag bit for 64-bit floats/ints). Strings are `u32 len` + UTF-8,
  zero-padded to a 4-byte boundary.

The codec round-trips byte-exactly (`write_variant(decode_blob(f)) == f[4:]`),
which is asserted in `shared/tests/test_variant.py`.

---

## Safety guarantees

- The app **only adds** `.blueprint` files inside `blueprints/`.
- All app state lives in `%LOCALAPPDATA%\FTNBlueprintLibrary\`
  (`settings.json`, `index.json`, `provenance.json`, `backups/`).
- Installs are refused while the game is running.
- Collisions are backed up before being renamed (`Name (2).blueprint`).
- Writes are atomic (`<name>.ftnlib.tmp` → `os.replace`); no partial files.
- Path-traversal names (`..\..\x.blueprint`, `C:\evil.blueprint`) are neutralised
  into plain filenames.

---

## Themes

Three built-in themes (`Needlework Light`, `Midnight Yard`, `Harvest Warm`) plus
**System**, all rendered from one shared QSS template × palette, switchable live
in Settings.
