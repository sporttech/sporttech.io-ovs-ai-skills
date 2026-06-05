# sporttech.io OVS AI Skills

External task recipes for AI agents working with packaged sporttech.io J3 OVS servers.

Agents should first read the server-local machine reference from `/api/ai`, then use this repository for task- and federation-specific workflows that do not belong in the Go server binary.

## Skill Index

The machine-readable index is published at:

`skills/index.json`

Each skill is a human-readable Markdown recipe. Recipes may reference `/api/ai` sections such as `constants`, `actions`, `fieldDocs`, `fieldFormats`, `importFormats`, and generated `fetchFlags`.
