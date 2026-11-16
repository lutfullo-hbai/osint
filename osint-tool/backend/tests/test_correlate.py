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
    # the GitHub profile itself publishes the investigated address: strong
    assert out["cluster_count"] == 1
    cluster = out["clusters"][0]
    assert len(cluster["members"]) == 2
    assert cluster["confidence"] == "high"
    assert "jane@doe.com" in cluster["identifiers"]["emails"]
    assert any("states the email" in s for s in cluster["signals"])


def test_name_search_handle_is_candidate_not_link():
    nodes = [
        {"key": "username:coolcoder", "type": "username", "query": "coolcoder",
         "results": []},
        {"key": "name:jane", "type": "name", "query": "Jane Roe", "results": [
            {"platform": "GitHub", "url": "https://github.com/coolcoder",
             "info": "Account whose display name matches."},
        ]},
    ]
    out = correlate(nodes)
    # a handle a NAME search surfaced is a namesake candidate, not identity:
    # it is listed on the name's cluster but never merged into it
    assert out["cluster_count"] == 2
    name_cluster = next(c for c in out["clusters"] if "name:jane" in c["members"])
    assert name_cluster["confidence"] == "single"
    assert [c["query"] for c in name_cluster["candidates"]] == ["coolcoder"]


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


def test_specific_handle_alone_is_a_candidate():
    # one medium signal (local-part == rare handle) is a lead, not a merge
    nodes = [
        {"key": "username:zephyrqx", "type": "username", "query": "zephyrqx",
         "results": [{"platform": "GitHub", "url": "https://github.com/zephyrqx"}]},
        {"key": "email:zephyrqx", "type": "email", "query": "zephyrqx@mail.com",
         "results": []},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 2
    cands = [c for cl in out["clusters"] for c in cl["candidates"]]
    assert cands and "email name reused as handle" in cands[0]["reason"]


def test_specific_handle_with_matching_name_links():
    nodes = [
        {"key": "username:zephyrqx", "type": "username", "query": "zephyrqx",
         "results": [{"platform": "GitHub", "url": "https://github.com/zephyrqx",
                      "info": "Name: Zephyr Quillfeather"}]},
        {"key": "email:zephyrqx", "type": "email", "query": "zephyrqx@mail.com",
         "results": [{"platform": "Gravatar", "url": "https://gravatar.com/z",
                      "info": "Name: Zephyr Quillfeather"}]},
    ]
    assert correlate(nodes)["cluster_count"] == 1


def test_contradiction_flagged_on_conflicting_locations():
    # strong evidence still links, but the conflict is reported
    nodes = [
        {"key": "username:sam", "type": "username", "query": "samsmith", "results": [
            {"platform": "Gravatar", "url": "https://gravatar.com/samsmith",
             "info": "Name: Sam Smith; Location: Toronto; Email: sam.smith.42@mail.com"},
        ]},
        {"key": "email:sam", "type": "email", "query": "sam.smith.42@mail.com", "results": [
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


def _name_hub(handles, via):
    """A name node that pivoted to several accounts, plus those accounts."""
    hub = {"key": "name:linus torvalds", "type": "name", "query": "Linus Torvalds",
           "results": [{"platform": "GitHub", "url": f"https://github.com/{h}",
                        "info": "Account whose display name matches."} for h in handles],
           "pivots": [{"type": "username", "value": h, "via": via} for h in handles]}
    kids = [{"key": f"username:{h.lower()}", "type": "username", "query": h,
             "results": [{"platform": "Lichess", "url": f"https://lichess.org/@/{h}"}]}
            for h in handles]
    return [hub, *kids]


def test_namesakes_from_display_name_match_are_not_merged():
    # regression: the Linus Torvalds deep scan glued 5 different people into
    # one HIGH cluster because each followed pivot counted as a shared handle
    nodes = _name_hub(["torvalds", "Linuuuus", "justin00314", "nthng-quan"], "name_match")
    out = correlate(nodes)
    assert out["cluster_count"] == 5
    assert all(c["confidence"] == "single" for c in out["clusters"])
    hub = next(c for c in out["clusters"] if "name:linus torvalds" in c["members"])
    assert len(hub["candidates"]) == 4


def test_knowledge_base_listed_account_links_high():
    nodes = _name_hub(["president_uz"], "knowledge_base")
    out = correlate(nodes)
    assert out["cluster_count"] == 1
    assert out["clusters"][0]["confidence"] == "high"
    assert any("knowledge base" in s for s in out["clusters"][0]["signals"])


def test_tagged_mention_is_not_identity():
    nodes = _name_hub(["TamimBinHamad"], "tagged")
    out = correlate(nodes)
    assert out["cluster_count"] == 2


def test_followed_handle_is_not_counted_twice():
    # username -> pivot to the same handle on an email local-part: the followed
    # handle must not also count as an independent "shared handle"
    nodes = [
        {"key": "email:zq@x.com", "type": "email", "query": "zephyrq@x.com",
         "results": [], "pivots": [{"type": "username", "value": "zephyrq",
                                    "via": "email_localpart"}]},
        {"key": "username:zephyrq", "type": "username", "query": "zephyrq",
         "results": []},
    ]
    out = correlate(nodes)
    # local-part reuse alone is weak: a candidate, never a merge
    assert out["cluster_count"] == 2
    email = next(c for c in out["clusters"] if "email:zq@x.com" in c["members"])
    assert email["candidates"][0]["query"] == "zephyrq"
    assert "shared handle" not in email["candidates"][0]["reason"]


def test_many_weak_links_never_add_up_to_high():
    # a hub tied to 3 nodes by one weak link each: confidence is the weakest
    # member's tie, not the sum of all links
    hub = {"key": "username:hubx", "type": "username", "query": "hubxyz", "results": [
        {"platform": "P", "url": f"https://github.com/{h}"} for h in ("aaaa1", "bbbb2", "cccc3")
    ]}
    kids = [{"key": f"username:{h}", "type": "username", "query": h, "results": []}
            for h in ("aaaa1", "bbbb2", "cccc3")]
    out = correlate([hub, *kids])
    # each tie is one weak shared handle: nothing merges, all are candidates
    assert all(len(c["members"]) == 1 for c in out["clusters"])
    assert all(c["confidence"] != "high" for c in out["clusters"])
    hub_cluster = next(c for c in out["clusters"] if "username:hubx" in c["members"])
    assert len(hub_cluster["candidates"]) == 3


def test_same_name_alone_is_a_candidate_not_a_link():
    # regression: namesake GitHub accounts showing "Name: Linus Torvalds"
    nodes = [
        {"key": "name:linus torvalds", "type": "name", "query": "Linus Torvalds", "results": []},
        {"key": "username:nthng-quan", "type": "username", "query": "nthng-quan", "results": [
            {"platform": "GitLab", "url": "https://gitlab.com/nthng-quan",
             "info": "Name: Linus Torvalds"}]},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 2
    hub = next(c for c in out["clusters"] if "name:linus torvalds" in c["members"])
    assert hub["candidates"][0]["query"] == "nthng-quan"


def test_same_name_still_corroborates_other_evidence():
    nodes = [
        {"key": "username:zephyrq", "type": "username", "query": "zephyrq", "results": [
            {"platform": "GitLab", "url": "https://gitlab.com/zephyrq", "info": "Name: Zed Quillfeather"}]},
        {"key": "email:z", "type": "email", "query": "zephyrq@mail.com", "results": [
            {"platform": "Gravatar", "url": "https://gravatar.com/zed", "info": "Name: Zed Quillfeather"}]},
    ]
    out = correlate(nodes)
    assert out["cluster_count"] == 1
    assert any("shared name" in s for s in out["clusters"][0]["signals"])


def test_candidates_are_unique_and_only_hang_off_the_name():
    nodes = [
        {"key": "name:n", "type": "name", "query": "Ann Lee", "results": [
            {"platform": "GitHub", "url": "https://github.com/annlee77"}],
         "pivots": [{"type": "username", "value": "annlee77", "via": "name_match"}]},
        {"key": "username:annlee77", "type": "username", "query": "annlee77", "results": [
            {"platform": "GitLab", "url": "https://gitlab.com/x", "info": "Name: Ann Lee"}]},
        {"key": "username:annl99", "type": "username", "query": "annl99", "results": [
            {"platform": "GitLab", "url": "https://gitlab.com/y", "info": "Name: Ann Lee"}]},
    ]
    out = correlate(nodes)
    hub = next(c for c in out["clusters"] if "name:n" in c["members"])
    assert sorted(x["query"] for x in hub["candidates"]) == ["annl99", "annlee77"]
    others = [c for c in out["clusters"] if "name:n" not in c["members"]]
    assert all(not c["candidates"] for c in others)
