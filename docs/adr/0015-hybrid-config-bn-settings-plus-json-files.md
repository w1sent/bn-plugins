# Hybrid config: BN Settings for simple values, complex config path as a BN Setting

Simple plugin settings (booleans, strings, numbers) are registered via BN's
native `Settings` API and appear in BN's Settings dialog. Complex nested
config (provider definitions, backoff steps, custom prompt paths) lives in
per-plugin JSON files. The path to each complex config file is itself a BN
Setting, so the user can discover and change it through BN's UI — no hidden
config locations.