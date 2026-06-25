#!/usr/bin/env bash
# scan transcripts -> claude -p -> proposals/<stamp>/proposals.json (5 drafted candidates)
# Read-only on transcripts. Writes only to build/ and proposals/. Never touches ~/.claude/skills.
set -euo pipefail
cd "$(dirname "$0")"

DAYS="${1:-30}"
mkdir -p build proposals

command -v claude >/dev/null || { echo "claude CLI not found on PATH"; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found on PATH"; exit 1; }

echo "[factory] scanning last $DAYS days..."
python3 scan.py --days "$DAYS" > build/digest.json

COUNT="$(python3 -c 'import json;print(json.load(open("build/digest.json"))["manual_multistep_turns"])')"
if [ "$COUNT" -eq 0 ]; then
  echo "[factory] No manual multi-step turns found in the last $DAYS days. Nothing to propose."
  exit 0
fi
echo "[factory] $COUNT candidate turns -> asking claude to cluster, rank, and draft 5 skills..."

# House-format reference: two REAL skills, read live so the format never goes stale.
EXAMPLES="$(printf '### EXAMPLE SKILL A (commit)\n'; cat "$HOME/.claude/skills/commit/SKILL.md" 2>/dev/null || echo '(commit skill not found)'
printf '\n### EXAMPLE SKILL B (humanize)\n'; cat "$HOME/.claude/skills/humanize/SKILL.md" 2>/dev/null || echo '(humanize skill not found)')"

read -r -d '' INSTRUCTIONS <<'EOF' || true
You are a skill-factory analyst. The DIGEST below is JSON describing recent MANUAL,
multi-step tasks the user did BY HAND in Claude Code. Turns already handled by an
existing skill are already excluded. Two real SKILL.md files show the house format.

Do this:
1. Cluster digest.candidates into recurring task TYPES by intent (not exact wording).
   Use bash_verb_freq and tool_shape_freq as supporting frequency evidence.
2. EXCLUDE any cluster already covered by a skill in digest.existing_skills.
3. Rank the TOP 5 clusters by impact = frequency x manual-effort-saved.
4. For EACH of the 5, write a COMPLETE SKILL.md matching the example format exactly:
   YAML frontmatter with name + description (and argument-hint ONLY if it uses
   $ARGUMENTS), an imperative markdown body, and a literal $ARGUMENTS at the end if used.

OUTPUT: a single JSON array of exactly 5 objects, NOTHING else (no prose, no code fence).
Each object has these keys:
  "name":        kebab-case skill name (must match the name: in its frontmatter)
  "description": one line (must match the description: in its frontmatter)
  "score":       number 1-10 (impact rank, highest first)
  "pillar":      short tag for the task type (e.g. "deploy", "scaffolding", "docs")
  "evidence":    one short paragraph: occurrence count, 1-2 representative example
                 requests from the digest, and which projects
  "skill_md":    the COMPLETE SKILL.md file as a single string (starts with ---)
Order the array by score, highest first. Output ONLY the JSON array.
EOF

PROMPT="$INSTRUCTIONS

== EXAMPLE SKILLS (house format) ==
$EXAMPLES

== DIGEST ==
$(cat build/digest.json)"

# claude is a shell alias (env -u ANTHROPIC_API_KEY claude); aliases don't apply in scripts,
# so spell it out. Never rely on ANTHROPIC_API_KEY. claude only reads; we own every write.
# Prompt goes via stdin (it can be 100KB+) to dodge ARG_MAX.
printf '%s' "$PROMPT" | env -u ANTHROPIC_API_KEY claude -p > build/llm_out.txt

STAMP="$(date +%F_%H%M%S)"
DIR="proposals/$STAMP"

python3 - "$DIR" build/llm_out.txt <<'PY'
import json, os, re, sys
d, src = sys.argv[1], sys.argv[2]
raw = open(src, encoding="utf-8").read().strip()
if raw.startswith("```"):                     # strip an outer fence if the model added one
    raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    if raw.rstrip().endswith("```"):
        raw = raw.rstrip()[:-3]
raw = raw.strip()
try:
    data = json.loads(raw)
except Exception as e:
    print("FAILED to parse claude output as JSON:", e, file=sys.stderr)
    print(raw[:600], file=sys.stderr)
    sys.exit(1)
if not isinstance(data, list):
    print("Expected a JSON array, got", type(data).__name__, file=sys.stderr)
    sys.exit(1)

os.makedirs(d, exist_ok=True)
clean = []
for c in data:
    name = (c.get("name") or "").strip()
    if not name:
        continue
    sm = (c.get("skill_md") or "").strip()
    if not sm:
        continue  # no drafted body -> uninstallable card; drop it
    sd = os.path.join(d, name)
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, "SKILL.md"), "w") as fh:
        fh.write(sm.rstrip() + "\n")
    clean.append({"name": name, "description": c.get("description", ""),
                  "score": c.get("score"), "pillar": c.get("pillar", ""),
                  "evidence": c.get("evidence", ""), "skill_md": sm})

with open(os.path.join(d, "proposals.json"), "w") as fh:
    json.dump({"stamp": os.path.basename(d), "candidates": clean}, fh, indent=2, ensure_ascii=False)
with open(os.path.join(d, "RANKING.md"), "w") as f:
    f.write("# Skill candidates\n\n")
    for i, c in enumerate(clean, 1):
        f.write(f"## {i}. {c['name']}  ({c.get('score')}/10)\n{c['description']}\n\n{c['evidence']}\n\n")
print(f"wrote {len(clean)} candidates to {d}")
PY

echo "[factory] done -> $DIR/proposals.json"
