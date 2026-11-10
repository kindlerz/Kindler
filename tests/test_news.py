from kindler.api.news import headline


def test_strips_matching_agency_suffix():
    entry = {"title": "Big story - Reuters", "source": {"title": "Reuters"}}
    assert headline(entry) == "Big story"


def test_keeps_title_without_agency():
    assert headline({"title": "Big story - Reuters"}) == "Big story - Reuters"
    entry = {"title": "Big story - Reuters", "source": {"title": ""}}
    assert headline(entry) == "Big story - Reuters"


def test_keeps_title_when_suffix_differs():
    entry = {"title": "Big story - Reuters", "source": {"title": "BBC"}}
    assert headline(entry) == "Big story - Reuters"


def test_strips_only_the_last_suffix():
    entry = {"title": "A - B - Reuters", "source": {"title": "Reuters"}}
    assert headline(entry) == "A - B"
