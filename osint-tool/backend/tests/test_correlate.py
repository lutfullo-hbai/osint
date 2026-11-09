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


def test_stoplist_handle_does_not_link():
    # "hello" is a common word -> must not glue two unrelated nodes
    nodes = [
        {"key": "username:hello", "type": "username", "query": "hello", "results": []},
        {"key": "email:hello", "type": "email", "query": "hello@other.com", "results": []},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 2  # not merged despite shared "hello"


def test_over_common_handle_does_not_link():
    # a handle seen on >= GENERIC_PLATFORM_THRESHOLD platforms is generic
    many = [
        {"platform": f"Site{i}", "url": "https://github.com/widget", "info": ""}
        for i in range(20)
    ]
    nodes = [
        {"key": "username:widget", "type": "username", "query": "widget",
         "results": many},
        {"key": "email:widget", "type": "email", "query": "widget@mail.com",
         "results": []},
    ]
    out = correlate(nodes)
    # "widget" appears on 20 platforms -> treated as generic -> no link
    assert out["cluster_count"] == 2


def test_specific_handle_still_links():
    # a rare handle on few platforms must still link (no regression)
    nodes = [
        {"key": "username:zephyrqx", "type": "username", "query": "zephyrqx",
         "results": [{"platform": "GitHub", "url": "https://github.com/zephyrqx"}]},
        {"key": "email:zephyrqx", "type": "email", "query": "zephyrqx@mail.com",
         "results": []},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 1


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
