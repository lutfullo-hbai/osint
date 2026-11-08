from services.correlate import correlate, nodes_from_findings, norm_handle


def test_norm_handle_strips_noise():
    assert norm_handle(" John.Doe ") == "johndoe"
    assert norm_handle("A_b-c") == "abc"


def test_unrelated_nodes_stay_separate():
    nodes = [
        {"key": "username:alice", "type": "username", "query": "alice", "results": []},
        {"key": "domain:bob.com", "type": "domain", "query": "bob.com", "results": []},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 2
    assert all(c["confidence"] == "single" for c in out["clusters"])


def test_shared_email_links_with_high_confidence():
    nodes = [
        {"key": "username:jdoe", "type": "username", "query": "jdoe", "results": [
            {"platform": "GitHub", "url": "https://github.com/jdoe",
             "info": "Email: jane@doe.com"},
        ]},
        {"key": "email:jane@doe.com", "type": "email", "query": "jane@doe.com",
         "results": []},
    ]
    out = correlate(nodes)
    # both the shared email AND the local-part==handle link should fire
    assert out["cluster_count"] == 1
    cluster = out["clusters"][0]
    assert len(cluster["members"]) == 2
    assert cluster["confidence"] == "high"
    assert "jane@doe.com" in cluster["identifiers"]["emails"]
    assert any("shared email" in s for s in cluster["signals"])


def test_shared_handle_links_medium():
    nodes = [
        {"key": "username:coolcoder", "type": "username", "query": "coolcoder",
         "results": []},
        {"key": "name:jane", "type": "name", "query": "Jane Roe", "results": [
            {"platform": "GitHub", "url": "https://github.com/coolcoder",
             "info": "Account whose display name matches."},
        ]},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 1
    # one shared handle alone is a weak link (score 2 -> low), by design
    assert out["clusters"][0]["confidence"] == "low"
    assert any("coolcoder" in s for s in out["clusters"][0]["signals"])


def test_short_handles_do_not_link():
    # "abc" is below MIN_HANDLE_LEN, so it must not glue unrelated nodes
    nodes = [
        {"key": "username:abc", "type": "username", "query": "abc", "results": []},
        {"key": "x", "type": "name", "query": "Zed Zoe", "results": [
            {"platform": "GitHub", "url": "https://github.com/abc", "info": ""},
        ]},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 2


def test_contradiction_flagged_on_conflicting_locations():
    nodes = [
        {"key": "username:sam", "type": "username", "query": "samsmith", "results": [
            {"platform": "Gravatar", "url": "https://gravatar.com/samsmith",
             "info": "Name: Sam Smith; Location: Toronto"},
        ]},
        {"key": "email:sam", "type": "email", "query": "samsmith@mail.com", "results": [
            {"platform": "Profile", "url": "https://keybase.io/samsmith",
             "info": "Location: Berlin"},
        ]},
    ]
    out = correlate(nodes)
    cluster = out["clusters"][0]
    assert len(cluster["members"]) == 2
    assert cluster["contradictions"]
    assert "Toronto" in cluster["contradictions"][0] and "Berlin" in cluster["contradictions"][0]


def test_nodes_from_findings_expands_deep_scan_and_maps_others():
    findings = [
        {"category": "domain", "query": "x.com", "result": {"results": [{"platform": "DNS"}]}},
        {"category": "deep_scan", "query": "y", "result": {"nodes": [
            {"key": "username:y", "type": "username", "query": "y", "results": []},
        ]}},
    ]
    nodes = nodes_from_findings(findings)
    keys = {n["key"] for n in nodes}
    assert "domain:x.com" in keys
    assert "username:y" in keys
    assert len(nodes) == 2
