"""Resolve source aliases without inventing evidence or guessing missing targets."""
import copy
import re


def resolve_references(result, known_sources):
    result = copy.deepcopy(result)
    ids = {e["id"] for e in result["evidence"]}
    claims = {c["id"] for c in result["claims"]}
    aliases, unresolved = {}, []
    declarations = []
    for claim in result["claims"]:
        linked = []
        for ref in claim["evidence"]:
            if ref in ids:
                linked.append(ref)
                continue
            if ref in aliases:
                linked.append(aliases[ref])
                continue
            matches = [e for e in result["evidence"] if e["source"] == ref]
            if len(matches) == 1:
                aliases[ref] = matches[0]["id"]
                linked.append(aliases[ref])
            elif ref.startswith("tool-artifact:") and ref in known_sources:
                number = len(ids) + 1
                while f"source_ref_{number}" in ids:
                    number += 1
                local = f"source_ref_{number}"
                ids.add(local)
                aliases[ref] = local
                result["evidence"].append({"id": local, "source": ref,
                    "text": "Direct reference to an existing saved source artifact. Inspect the artifact for its contents; this linkage alone does not verify the claim."})
                linked.append(local)
            else:
                unresolved.append({"claim": claim["id"], "relation": "evidence", "target": ref})
        claim["evidence"] = list(dict.fromkeys(linked))
        dangling = [ref for ref in claim["contradicts"] if ref not in claims]
        unresolved.extend({"claim": claim["id"], "relation": "contradicts", "target": ref} for ref in dangling)
        claim["contradicts"] = [ref for ref in claim["contradicts"] if ref in claims]
        linked_assumptions = []
        for ref in claim["assumptions"]:
            if ref in result["assumptions"]:
                linked_assumptions.append(ref)
            elif len(ref.split()) >= 3 and not re.fullmatch(r"(?:a|assumption|assump|h|hypothesis)[\s_:#-]*\d+", ref.strip(), re.I):
                # The worker already supplied the statement verbatim. Register
                # its declaration without paraphrasing or asserting it is true.
                result["assumptions"].append(ref)
                linked_assumptions.append(ref)
                declarations.append({"claim": claim["id"], "text": ref})
            else:
                unresolved.append({"claim": claim["id"], "relation": "assumptions", "target": ref})
        claim["assumptions"] = linked_assumptions
    if declarations:
        result["registered_assumptions"] = declarations
        result["limitations"].append("Missing assumption declarations were copied verbatim from claims; they remain model-provided assumptions, not verified facts.")
    if unresolved:
        result["unresolved_references"] = unresolved
        result["limitations"].append("Some reasoning links could not be resolved and are not counted as evidence, contradiction or assumption edges: " + "; ".join(f"{r['claim']} -> {r['relation']} -> {r['target']}" for r in unresolved))
    return result
