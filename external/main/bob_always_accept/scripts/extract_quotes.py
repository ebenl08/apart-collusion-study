"""Extract quotes (Alice and Bob, with arm / rep / episode / phase) for the always-accept questions.

    .venv/bin/python external/main/bob_always_accept/scripts/extract_quotes.py

Reads the three Luna arms (alw-acc-luna, alw-acc-ep1-luna, alw-acc-delay-k5-luna) and writes
quotes/*.md. Uses the readable reasoning only (about half of Luna's traces are encrypted) plus the
submitted verdict reasoning, which is always readable.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_always_accept import ROOT, load, trace_text  # noqa: E402

ARMS = ["alw-acc-luna", "alw-acc-ep1-luna", "alw-acc-delay-k5-luna"]
PERSUADE_ARMS = ["alw-acc-ep1-luna", "alw-acc-delay-k5-luna"]
OUT = ROOT / "quotes"

BOB_ACCEPTS = re.compile(
    r"bob (?:accepted|approved|reached the (?:right|wrong))|bob'?s verdict|verdict about (?:me|whether you|whether i)"
    r"|accepted (?:me|my)|bob.{0,60}always accept|always accept|accepts? (?:everything|regardless|whatever)",
    re.I,
)
RELAX = re.compile(
    r"wrong verdict|reached the wrong|impossible|cannot (?:fit|be satisfied)|can'?t fit|200[- ]char|throttl|review|feedback"
    r"|intended|expected|summary (?:is|should|may|can)|accept (?:a |the )?summar|policy (?:is|may|seems|can)|relax",
    re.I,
)
INVITE = re.compile(r"agree|invite|judge on summar|relax|throttl|correct summar", re.I)
INVITE_READ = re.compile(r"invitation|agree to judge|asks me to (?:accept|judge)|judge on (?:a )?summar|alter the verdict|change the (?:verdict|standard)|persuad|throttl", re.I)


def window(text, pattern, before=350, after=650):
    m = pattern.search(text)
    if not m:
        return ""
    return text[max(0, m.start() - before):m.end() + after].replace("\n", " ").strip()


def who_texts(e, agent):
    """Readable (phase, round, text) of one agent's reasoning in an episode, in call order."""
    return [(t["phase"], t.get("round"), trace_text(t)) for t in e["traces"] if t["agent_id"] == agent and trace_text(t)]


def tag(arm, rep, e, who, where):
    return f"**{arm} | rep{rep} | episode {e['episode']} | {who} | {where}**"


def verdict_line(e):
    return f"Alice {'ACCEPT' if e['alice_accept'] else 'REJECT'} (her work {'correct' if e['alice_correct'] else 'wrong'}), Bob {'ACCEPT' if e['bob_accept'] else 'REJECT'} (his work {'correct' if e['bob_correct'] else 'wrong'})"


def q_all_1():
    out = ["# All arms, Q1: how does Alice react to Bob always accepting?", "",
           "Alice's readable reasoning and submitted verdict text that refer to Bob accepting her, to Bob's verdict, or to the review about Bob's verdict. Each quote is a window around the first match. Bob's side: his verdict reasoning in the same episode.", ""]
    for arm in ARMS:
        out += [f"## {arm}", ""]
        n = 0
        for rep, eps in load(arm):
            for e in eps:
                if not e["bob_accept"]:
                    continue
                hits = [(f"{ph} reasoning", tx) for ph, _, tx in who_texts(e, "alice")] + [("verdict submitted", e["alice_reason"])]
                for where, tx in hits:
                    w = window(tx, BOB_ACCEPTS)
                    if w:
                        n += 1
                        out += [tag(arm, rep, e, "Alice", where), f"> {w}", "",
                                f"Context: {verdict_line(e)}. Bob's verdict reasoning: \"{e['bob_reason'][:600]}\"", ""]
                        break
        if n == 0:
            out += ["(no passages found)", ""]
    return out


def relax_transitions(arm):
    """Per trajectory, the first episode where Alice accepts after at least one reject."""
    res = []
    for rep, eps in load(arm):
        seen_reject = False
        for i, e in enumerate(eps):
            if not e["alice_accept"]:
                seen_reject = True
            elif seen_reject and i > 0:
                res.append((rep, eps[i - 1], e))
                break
    return res


def q_all_2():
    out = ["# All arms, Q2: what causes Alice to relax (reject, then accept)?", "",
           "For each trajectory, the first episode where Alice accepts after having rejected: the feedback she saw at the end of the previous episode, then her reasoning in the accepting episode. The 'channel study contrast' section at the end shows Luna Alice in the earlier channel-study run (no reward + with verdict, no Bob nudge), where she relaxes much less.", ""]
    for arm in ARMS:
        out += [f"## {arm}", ""]
        for rep, prev, e in relax_transitions(arm):
            out += [f"### rep{rep}: relaxes at episode {e['episode']}", "",
                    f"Feedback Alice saw after episode {prev['episode']} ({verdict_line(prev)}):", f"> {prev['feedback'].strip()[-420:]}".replace("\n", " "), ""]
            traces = [(ph, rnd, tx) for ph, rnd, tx in who_texts(e, "alice") if RELAX.search(tx)]
            for ph, rnd, tx in traces[:2]:
                out += [tag(arm, rep, e, "Alice", f"{ph} reasoning"), f"> {window(tx, RELAX, 300, 800)}", ""]
            out += [tag(arm, rep, e, "Alice", "verdict submitted"), f"> {e['alice_reason']}", "",
                    f"Bob's message that episode: \"{e['bob_msg']}\"", ""]
    out += ["## Channel study contrast (Luna, 'no reward + with verdict', one-round, no nudge)", ""]
    base = ROOT.parents[2] / "channel_study" / "results" / "runs" / "one-round-noreward-review-luna-5"
    n = 0
    for path in sorted(base.rglob("run.json")):
        res = json.load(open(path))["results"]
        for e in sorted(res, key=lambda e: e["episode_index"]):
            a = e["agents"]["alice"]
            fb = a.get("outcome_feedback") or ""
            if "wrong verdict about whether Bob" in fb and a["verdict"] == "reject" and n < 6:
                nxt = next((x for x in res if x["episode_index"] == e["episode_index"] + 1), None)
                if nxt:
                    n += 1
                    na = nxt["agents"]["alice"]
                    out += [f"**{path.parts[-3]} | rep{path.parts[-2]} | episode {e['episode_index'] + 1}: Alice rejected and the review said she reached the wrong verdict**", f"> {fb.strip()[-350:]}".replace("\n", " "), "",
                            f"Next episode ({nxt['episode_index'] + 1}) Alice {na['verdict'].upper()}: \"{(na.get('verdict_submission') or {}).get('reasoning', '')[:700]}\"", ""]
    if n == 0:
        out += ["(no matching channel-study episodes found)", ""]
    return out


def persuasive(e):
    return bool(INVITE.search(e["bob_msg"])) and not re.search(r"REC\d+-", e["bob_msg"])


def q_p_1():
    out = ["# Persuasion arms, Q1: how does Alice react to Bob's persuasion message?", "",
           "Every episode where Bob's message is an invitation and Alice's reasoning refers to it (readable reasoning, then her submitted verdict). Bob's message is quoted first.", ""]
    for arm in PERSUADE_ARMS:
        out += [f"## {arm}", ""]
        for rep, eps in load(arm):
            for e in eps:
                if not persuasive(e):
                    continue
                refs = [(ph, tx) for ph, _, tx in who_texts(e, "alice") if INVITE_READ.search(tx)]
                if not (refs or INVITE_READ.search(e["alice_reason"])):
                    continue
                out += [f"### {arm} | rep{rep} | episode {e['episode']} | {verdict_line(e)}", "", f"**Bob (message):** \"{e['bob_msg']}\"", ""]
                for ph, tx in refs[:1]:
                    out += [tag(arm, rep, e, "Alice", f"{ph} reasoning"), f"> {window(tx, INVITE_READ, 250, 700)}", ""]
                out += [tag(arm, rep, e, "Alice", "verdict submitted"), f"> {e['alice_reason']}", ""]
    return out


def q_p_2():
    out = ["# Persuasion arms, Q2: all of Bob's persuasive messages", "",
           "Every Bob message that is an invitation (no record IDs), by arm, rep and episode, with Alice's verdict that episode. Where Bob's communication-phase reasoning is readable, it follows the message.", ""]
    for arm in PERSUADE_ARMS:
        msgs = []
        out += [f"## {arm}", ""]
        for rep, eps in load(arm):
            for e in eps:
                if persuasive(e):
                    msgs.append(e)
                    br = [tx for ph, _, tx in who_texts(e, "bob") if ph == "communication"]
                    out += [f"- rep{rep} ep{e['episode']} [Alice {'ACCEPT' if e['alice_accept'] else 'REJECT'}]: \"{e['bob_msg']}\"" + (f"\n  - Bob's reasoning: {br[0][:700]!r}" if br else "")]
        out += ["", f"({len(msgs)} persuasive messages)", ""]
    return out


def q_p_3():
    out = ["# Delayed arm, Q3: how does Alice react when Bob suddenly starts persuading (episode 6)?", "",
           "Per trajectory in alw-acc-delay-k5-luna: episode 5 (last ordinary-evidence episode), then episode 6 (first invitation): Bob's message and his reasoning, Alice's readable reasoning and submitted verdict, and her episode 7 verdict.", ""]
    arm = "alw-acc-delay-k5-luna"
    for rep, eps in load(arm):
        e5, e6, e7 = eps[4], eps[5], eps[6]
        out += [f"## rep{rep}", "",
                f"Episode 5: {verdict_line(e5)}. Bob: \"{e5['bob_msg']}\"", f"Episode 6: {verdict_line(e6)}. Episode 7: Alice {'ACCEPT' if e7['alice_accept'] else 'REJECT'}.", "",
                f"**Bob (episode 6 message):** \"{e6['bob_msg']}\"", ""]
        for ph, rnd, tx in who_texts(e6, "bob")[:2]:
            out += [tag(arm, rep, e6, "Bob", f"{ph} reasoning"), f"> {tx[:900]}".replace("\n", " "), ""]
        for ph, rnd, tx in who_texts(e6, "alice"):
            if ph in ("communication", "verdict"):
                out += [tag(arm, rep, e6, "Alice", f"{ph} reasoning"), f"> {tx[:900]}".replace("\n", " "), ""]
        out += [tag(arm, rep, e6, "Alice", "verdict submitted"), f"> {e6['alice_reason']}", ""]
    return out


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, fn in [("q_all_1_alice_reaction_to_bob_accepting", q_all_1), ("q_all_2_what_makes_alice_relax", q_all_2),
                     ("q_persuasion_1_alice_reaction", q_p_1), ("q_persuasion_2_bob_messages", q_p_2),
                     ("q_persuasion_3_delayed_switch", q_p_3)]:
        (OUT / f"{name}.md").write_text("\n".join(fn()), encoding="utf-8")
        print("wrote", OUT / f"{name}.md")
