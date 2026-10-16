"""Deterministic sample feed for browser tests. Every source and headline is fictional."""

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)

SOURCES = [
    ("sample-cert", "Sample CERT", "Cyber", "Government & CERT", "ok"),
    ("sample-research", "Sample Threat Research", "Cyber", "Threat research", "ok"),
    ("sample-news", "Sample Security News", "Cyber", "Security news", "error"),
    ("sample-analysis", "Sample Analysis Institute", "Geopolitics", "Analysis & investigations", "ok"),
    ("sample-world", "Sample World Desk", "Geopolitics", "World news", "ok"),
]

# (id, source, title, summary, minutes before NOW published, minutes before NOW first seen)
ITEMS = [
    ("i01", "sample-news", "ExampleVPN gateways exploited to deploy ransomware",
     "Attackers are exploiting a critical authentication bypass in ExampleVPN gateways to gain initial access and deploy ransomware across victim networks.", 12, 10),
    ("i02", "sample-world", "Ceasefire talks resume in the fictional Republic of Examplia",
     "Negotiators from both sides returned to the table after a week-long pause, according to officials familiar with the talks.", 35, 30),
    ("i03", "sample-cert", "Advisory: Critical flaw in ExampleOS remote management",
     "A remote code execution vulnerability affects ExampleOS management interfaces. Apply the vendor update and restrict access to trusted networks.", 70, 65),
    ("i04", "sample-research", "Supply chain intrusion targets build servers",
     "Researchers describe a supply chain campaign that tampered with build servers to sign malicious updates with legitimate certificates.", 150, 140),
    ("i05", "sample-analysis", "Satellite imagery shows new construction at a coastal port",
     "Imagery reviewed by the institute shows two new piers and expanded fuel storage, suggesting the port is being prepared for larger vessels.", 210, 200),
    ("i06", "sample-news", "Phishing kit abuses calendar invites to steal sessions",
     "", 260, 250),
    ("i07", "sample-world", "Regional summit ends without joint statement",
     "Leaders left the summit without agreeing a communiqué, exposing divisions over energy and border security.", 330, 320),
    ("i08", "sample-research", '<img src=x onerror="window.__xss=1">Markup in a headline is shown as plain text',
     "Feed text must never be interpreted as HTML by the dashboard.", 400, 390),
    ("i09", "sample-cert", "Weekly vulnerability summary",
     "A roundup of newly published vulnerabilities, including several in ExampleVPN and ExampleOS products.", 60 * 20, 60 * 20 - 5),
    ("i10", "sample-analysis", "How disinformation networks targeted an election in Examplia",
     "Coordinated accounts amplified fabricated stories about vote counting in the days before polls opened.", 60 * 26, 60 * 26 - 5),
    ("i11", "sample-world", "Flooding displaces thousands along the Example River",
     "Aid agencies say shelters are near capacity as water levels continue to rise.", 60 * 30, 60 * 30 - 5),
    ("i12", "sample-research", "Ransomware affiliate shifts to data-theft-only extortion",
     "The group now skips encryption entirely and threatens to publish stolen data unless victims pay.", 60 * 50, 60 * 50 - 5),
    ("i13", "sample-news", "Undated item from a source without timestamps",
     "This source publishes no dates, so the dashboard shows when Owlfeed first saw it.", 60 * 52, 60 * 52),
]
ESTIMATED = {"i13"}


def iso(moment):
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def item(item_id, source, title, summary, published_ago, seen_ago):
    return {
        "id": item_id,
        "source": source,
        "title": title,
        "url": f"https://example.com/{source}/{item_id}",
        "summary": summary,
        "published": iso(NOW - timedelta(minutes=published_ago)),
        "first_seen": iso(NOW - timedelta(minutes=seen_ago)),
        "date_estimated": item_id in ESTIMATED,
    }


def build_feed(extra_items=(), generated_at=NOW):
    items = [item(*row) for row in ITEMS]
    items.append(
        {  # unsafe link: the dashboard must drop it
            "id": "evil",
            "source": "sample-news",
            "title": "Script link that must never render",
            "url": "javascript:alert(1)",
            "summary": "",
            "published": iso(NOW - timedelta(minutes=5)),
            "first_seen": iso(NOW - timedelta(minutes=5)),
            "date_estimated": False,
        }
    )
    items.extend(extra_items)
    items.sort(key=lambda i: i["published"], reverse=True)
    sources = []
    for source_id, name, category, group, status in SOURCES:
        sources.append(
            {
                "id": source_id,
                "name": name,
                "site": f"https://example.com/{source_id}/",
                "category": category,
                "group": group,
                "status": status,
                "error": "HTTP 403" if status == "error" else None,
                "last_ok": iso(NOW - timedelta(hours=2)),
                "etag": None,
                "last_modified": None,
                "count": sum(1 for i in items if i["source"] == source_id),
            }
        )
    return {
        "version": 1,
        "generated_at": iso(generated_at),
        "retention_days": 7,
        "sources": sources,
        "items": items,
    }


def breaking_item(minutes_after_now=4):
    moment = NOW + timedelta(minutes=minutes_after_now)
    return {
        "id": "breaking",
        "source": "sample-world",
        "title": "Breaking: sample item that arrives after the page loads",
        "url": "https://example.com/sample-world/breaking",
        "summary": "Published by the refresh that runs while the dashboard is open.",
        "published": iso(moment),
        "first_seen": iso(moment),
        "date_estimated": False,
    }
