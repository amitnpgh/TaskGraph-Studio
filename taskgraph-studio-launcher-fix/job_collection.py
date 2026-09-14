"""Counted, source-linked job inventories; source presence is not vacancy verification."""
import copy
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def requested_jobs(goal):
    match = re.search(r"\b(?:list\s+of\s+|find\s+(?:me\s+)?|give\s+me\s+)(\d+)\b", goal, re.I)
    return int(match[1]) if match and re.search(r"\b(jobs|openings|vacancies|positions)\b", goal, re.I) else None


def canonical(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def source_urls(value):
    urls = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str) and canonical(item):
                urls.add(canonical(item))
            else:
                urls.update(source_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.update(source_urls(item))
    return urls


def result_schema(base):
    schema = copy.deepcopy(base)
    fields = {key: {"type": "string"} for key in ("title", "organization", "location", "url", "source", "status_note")}
    schema["properties"]["job_items"] = {"type": "array", "items": {
        "type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}
    schema["required"].append("job_items")
    return schema


def vacancy_url(url):
    """Reject recognizable board indexes; this is not a page-content verifier."""
    parts = urlsplit(url)
    path = [p for p in parts.path.split("/") if p]
    host = (parts.hostname or "").lower()
    if host in {"jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com"}:
        return len(path) >= 2
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if path == ["embed", "job_app"]:
            return any(k == "token" and v for k, v in parse_qsl(parts.query))
        return len(path) >= 3 and "jobs" in path
    if not path or parts.path.rstrip("/").lower() in {"/jobs", "/careers", "/openings", "/positions"}:
        return any(k in {"gh_jid", "jobid", "job_id", "requisitionId"} and v for k, v in parse_qsl(parts.query))
    return True


def merge_items(prior, proposed, sources):
    """Never silently replace an existing record with another synthesized version."""
    result = {}
    issues = []
    for item in list(prior) + list(proposed):
        url = canonical(item["url"])
        if not vacancy_url(item["url"]):
            issues.append("Job-board index excluded; retrieve an individual vacancy URL: " + item["url"])
            continue
        if not url or url not in sources.get(item["source"], set()):
            issues.append("Listing lacks a matching retrieved source: " + item["url"])
            continue
        if not item["title"].strip() or not item["organization"].strip():
            issues.append("Listing lacks a title or employer: " + item["url"])
            continue
        if url in result and item != result[url]:
            issues.append("Conflicting replacement ignored; check original listing: " + item["url"])
            continue
        identity = tuple(re.sub(r"\W+", "", item[k].casefold()) for k in ("organization", "title", "location"))
        if any(tuple(re.sub(r"\W+", "", old[k].casefold()) for k in ("organization", "title", "location")) == identity for old in result.values()):
            continue
        result[url] = item
    return list(result.values()), issues


def render(items, target):
    lines = [f"Job listings: {len(items)} of {target} requested.",
             ("Each entry links to retrieved source material. Status notes describe verification limits."
              if items else "No source-linked job listings were collected. This is not a completed job list."), ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['organization']} — {item['title']} — {item['location']}\n   {item['url']}\n   Status: {item['status_note']}\n   Evidence: {item['source']}")
    return "\n".join(lines)


def reconcile_review(rows, items):
    """Join by vacancy identity; never invent approval for an unmatched record."""
    expected = {canonical(item["url"]): item["url"] for item in items}
    grouped = {key: [] for key in expected}
    ignored = []
    for row in rows:
        key = canonical(row["url"])
        if key not in grouped:
            ignored.append(row["url"])
        else:
            grouped[key].append(row)
    result = []
    for key, original in expected.items():
        matches = grouped[key]
        classes = {row["classification"] for row in matches}
        if len(classes) == 1 and classes <= {"supported", "ambiguous", "unsupported"}:
            result.append({**matches[0], "url": original})
        else:
            result.append({"url": original, "classification": "ambiguous",
                           "reason": "No consistent valid verdict was returned for this listing; it is not approved."})
    return {"rows": result}, ignored
