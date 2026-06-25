#!/usr/bin/env python3
"""Distill recent Claude Code transcripts + usage log into a small JSON digest of
the repetitive, multi-step tasks Jordan does BY HAND (no skill attached).

Read-only on transcripts. Streams line-by-line. The LLM (see factory.sh) does the
clustering/ranking/drafting; this script only filters (manual + multi-step) and
compresses (truncate + cap). Stdlib only.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

# Bash command heads that are just dispatchers — keep two tokens so "git push" /
# "docker compose" carry signal instead of collapsing to "git" / "docker".
MULTIPLEX = {"git", "npm", "npx", "pnpm", "yarn", "docker", "gh", "firebase",
             "php", "kubectl", "cargo", "node", "python", "python3", "make", "brew"}
# Heads that carry no task signal — skip past them to the real verb in a segment.
# Read-only inspection verbs included: they're how Claude explores, not a task signature.
TRIVIAL = {"cd", "echo", "export", "source", "set", "true", ":", "ls", "cat", "pwd",
           "grep", "rg", "tail", "head", "sed", "awk", "find", "wc", "jq", "cut",
           "sort", "uniq", "tr", "which", "command", "printf", "test", "less", "diff",
           "basename", "dirname", "realpath", "stat", "file", "sleep", "date",
           # shell/JS keywords that leak out of for-loops, heredocs and `node -e`
           "do", "done", "then", "fi", "else", "elif", "for", "while", "in", "case",
           "if", "const", "let", "var", "function", "return"}


def extract_text(content):
    """First non-empty text block of a message, or None (tool_result-only msgs -> None)."""
    if isinstance(content, str):
        return content if content.strip() else None
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        parts = [p for p in parts if p and p.strip()]
        if parts:
            return "\n".join(parts)
    return None


def is_user_prompt(o):
    """A genuine user turn boundary — not isMeta, not a tool_result continuation."""
    if o.get("type") != "user" or o.get("isMeta"):
        return False
    return extract_text((o.get("message") or {}).get("content")) is not None


def is_command(text):
    return "<command-name>" in text or "<command-message>" in text


def bash_verb(cmd):
    """Most informative verb of a bash command (handles && ; | chains)."""
    cmd = (cmd or "").strip()
    if not cmd:
        return None
    segs = re.split(r"&&|\|\||;|\|", cmd)
    for seg in segs:
        toks = seg.split()
        if not toks:
            continue
        base = toks[0].split("/")[-1]
        if base in TRIVIAL:
            continue
        if base in MULTIPLEX and len(toks) >= 2 and not toks[1].startswith("-"):
            return base + " " + toks[1]
        return base
    return None  # all segments were trivial/inspection -> no task signal


def assistant_tools(o):
    """(ordered tool names, bash verbs) from an assistant message."""
    tools, bash = [], []
    for b in (o.get("message") or {}).get("content") or []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            name = b.get("name")
            tools.append(name)
            if name == "Bash":
                v = bash_verb((b.get("input") or {}).get("command", ""))
                if v:
                    bash.append(v)
    return tools, bash


def clean(text):
    return re.sub(r"\s+", " ", text).strip()[:200]


def new_turn(o, text):
    cwd = o.get("cwd") or ""
    return {"ts": o.get("timestamp"), "project": cwd.split("/")[-1] if cwd else "",
            "request": clean(text), "tools": [], "bash_verbs": [],
            "attributed": False, "is_command": is_command(text)}


def turns_from_objs(objs):
    """Reconstruct conversation turns from parsed JSONL objects. Pure -> testable."""
    turns, cur = [], None
    for o in objs:
        if is_user_prompt(o):
            if cur is not None:
                turns.append(cur)
            cur = new_turn(o, extract_text((o.get("message") or {}).get("content")))
        elif o.get("type") == "assistant" and cur is not None:
            if o.get("attributionSkill"):
                cur["attributed"] = True
            tools, bash = assistant_tools(o)
            cur["tools"].extend(tools)
            cur["bash_verbs"].extend(bash)
    if cur is not None:
        turns.append(cur)
    return turns


def is_manual_multistep(t):
    if t["attributed"] or t["is_command"]:
        return False
    return len(t["tools"]) >= 2 or len(t["bash_verbs"]) >= 1


def parse_file(path):
    objs = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except (ValueError, TypeError):
                continue  # skip malformed / truncated lines
    return turns_from_objs(objs)


def usage_counts(path):
    c = collections.Counter()
    if not os.path.exists(path):
        return c
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1]:
                c[parts[1]] += 1  # field 2 = skill name (mirrors log-skill.sh)
    return c


def build_digest(days, max_candidates, projects_dir, skills_dir, usage_log):
    cutoff = None
    try:
        import time
        cutoff = time.time() - days * 86400
    except Exception:
        cutoff = 0

    files = glob.glob(os.path.join(projects_dir, "*", "*.jsonl"))
    files = [f for f in files if os.path.getmtime(f) >= cutoff]

    all_turns = []
    for f in files:
        try:
            all_turns.extend(parse_file(f))
        except OSError:
            continue

    kept = [t for t in all_turns if is_manual_multistep(t)]
    kept.sort(key=lambda t: t.get("ts") or "", reverse=True)

    bash_freq = collections.Counter()
    shape_freq = collections.Counter()
    for t in kept:
        bash_freq.update(t["bash_verbs"])
        if t["tools"]:
            shape_freq[">".join(t["tools"][:6])] += 1

    capped = kept[:max_candidates]
    candidates = [{"ts": t["ts"], "project": t["project"], "request": t["request"],
                   "tools": t["tools"], "bash_verbs": t["bash_verbs"]} for t in capped]

    existing = sorted(d for d in (os.listdir(skills_dir) if os.path.isdir(skills_dir) else [])
                      if os.path.isdir(os.path.join(skills_dir, d)))
    usage = usage_counts(usage_log)

    return {
        "generated_for_days": days,
        "transcripts_scanned": len(files),
        "turns_total": len(all_turns),
        "manual_multistep_turns": len(kept),
        "dropped_due_to_cap": len(kept) - len(capped),
        "existing_skills": existing,
        "top_existing_skill_usage": dict(usage.most_common(25)),
        "bash_verb_freq": dict(bash_freq.most_common(40)),
        "tool_shape_freq": dict(shape_freq.most_common(30)),
        "candidates": candidates,
    }


def selfcheck():
    """Tiny synthetic transcript through the parser. The one runnable check."""
    objs = [
        # manual multi-step turn: Bash -> Edit -> Bash, no skill
        {"type": "user", "cwd": "/x/proj", "timestamp": "2026-06-20T10:00:00Z",
         "message": {"content": [{"type": "text", "text": "fix the build then commit"}]}},
        {"type": "assistant",
         "message": {"content": [{"type": "tool_use", "name": "Bash",
                                  "input": {"command": "cd /x && npm run build"}}]}},
        {"type": "user",  # tool_result continuation — must NOT start a new turn
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant",
         "message": {"content": [{"type": "tool_use", "name": "Edit",
                                  "input": {"file_path": "a.js"}}]}},
        {"type": "assistant",
         "message": {"content": [{"type": "tool_use", "name": "Bash",
                                  "input": {"command": "git commit -m x"}}]}},
        # skill-attributed turn — must be dropped
        {"type": "user", "message": {"content": [{"type": "text", "text": "summarize this"}]}},
        {"type": "assistant", "attributionSkill": "sessions",
         "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
        # typed slash command — must be dropped
        {"type": "user", "message": {"content": [{"type": "text",
            "text": "<command-message>commit</command-message>\n<command-name>/commit</command-name>"}]}},
        {"type": "assistant",
         "message": {"content": [{"type": "tool_use", "name": "Bash",
                                  "input": {"command": "git push"}}]}},
    ]
    turns = turns_from_objs(objs)
    assert len(turns) == 3, f"expected 3 turns, got {len(turns)}"
    manual = [t for t in turns if is_manual_multistep(t)]
    assert len(manual) == 1, f"expected 1 manual turn, got {len(manual)}"
    m = manual[0]
    assert m["tools"] == ["Bash", "Edit", "Bash"], m["tools"]
    assert m["bash_verbs"] == ["npm run", "git commit"], m["bash_verbs"]
    assert m["request"] == "fix the build then commit", m["request"]
    # the dropped two are correctly classified
    assert any(t["attributed"] for t in turns), "skill turn not flagged attributed"
    assert any(t["is_command"] for t in turns), "slash turn not flagged is_command"
    assert bash_verb("cd /x && git push origin main") == "git push"
    assert bash_verb("docker compose up -d") == "docker compose"
    assert bash_verb("grep -r foo . | head") is None  # pure inspection -> no signal
    assert bash_verb("ls -la") is None
    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--max", type=int, default=300, dest="max_candidates")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--usage-log", default=os.path.expanduser("~/.claude/skill-usage.log"))
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        selfcheck()
        return

    digest = build_digest(args.days, args.max_candidates, args.projects_dir,
                          args.skills_dir, args.usage_log)
    print(json.dumps(digest, indent=2, ensure_ascii=False))
    print(f"[scan] {digest['transcripts_scanned']} transcripts, "
          f"{digest['manual_multistep_turns']} manual multi-step turns "
          f"({digest['dropped_due_to_cap']} dropped by --max)", file=sys.stderr)


if __name__ == "__main__":
    main()
