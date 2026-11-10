import pytest

from downverse.links import KIND_CHANNEL, KIND_LIVE, LinkError, parse_link

CHANNEL = "https://weverse.io/lesserafim/live"


@pytest.mark.parametrize("text", [
    "https://weverse.io/lesserafim",
    "https://weverse.io/lesserafim/",
    "http://weverse.io/lesserafim",
    "https://www.weverse.io/lesserafim",
    "https://m.weverse.io/lesserafim",
    "weverse.io/lesserafim",
    "WEVERSE.IO/LeSserafim",
    "  https://weverse.io/lesserafim  ",
    "<https://weverse.io/lesserafim>",
    '"https://weverse.io/lesserafim"',
    "https://weverse.io/lesserafim?hl=ko",
    "https://weverse.io/lesserafim#top",
    "https://weverse.io/lesserafim/live",
    "https://weverse.io/lesserafim/live/",
    "https://weverse.io/lesserafim/live?hl=pt-br&utm_source=x",
    "https://weverse.io/lesserafim/live/schedule",
    "https://weverse.io/en/lesserafim/live",
    "https://weverse.io/lesserafim/feed",
    "https://weverse.io/lesserafim/artist",
    "https://weverse.io/lesserafim/highlight",
    "https://weverse.io/lesserafim/media",
    "https://weverse.io/lesserafim/media/all",
    "Veja as lives dela aqui: https://weverse.io/lesserafim/live.",
])
def test_channel_links_all_resolve_to_the_live_tab(text):
    link = parse_link(text)
    assert link.kind == KIND_CHANNEL
    assert link.community == "lesserafim"
    assert link.url == CHANNEL
    assert link.post_id is None


@pytest.mark.parametrize("text", [
    "https://weverse.io/lesserafim/live/2-102331763",
    "https://weverse.io/lesserafim/live/2-102331763/",
    "https://weverse.io/lesserafim/live/2-102331763?hl=en",
    "https://weverse.io/lesserafim/live/2-102331763#comments",
    "https://weverse.io/lesserafim/live/2-102331763/comment",
    "weverse.io/lesserafim/live/2-102331763",
    "https://m.weverse.io/lesserafim/live/2-102331763",
    "olha essa live https://weverse.io/lesserafim/live/2-102331763, muito boa!",
    "(https://weverse.io/lesserafim/live/2-102331763)",
    "https://weverse.io/ko/lesserafim/live/2-102331763",
])
def test_single_live_links(text):
    link = parse_link(text)
    assert link.kind == KIND_LIVE
    assert link.community == "lesserafim"
    assert link.post_id == "2-102331763"
    assert link.url == "https://weverse.io/lesserafim/live/2-102331763"


def test_media_vod_link_is_kept_as_media():
    link = parse_link("https://weverse.io/billlie/media/3-102914520")
    assert (link.kind, link.post_id) == (KIND_LIVE, "3-102914520")
    assert link.url == "https://weverse.io/billlie/media/3-102914520"


def test_post_from_another_tab_is_tried_as_live():
    link = parse_link("https://weverse.io/lesserafim/artist/2-102331763")
    assert link.kind == KIND_LIVE and link.url.endswith("/live/2-102331763")
    assert link.note


def test_multiple_links_use_the_first_and_warn():
    link = parse_link("https://weverse.io/a/live/1-1 https://weverse.io/b/live/2-2")
    assert link.community == "a" and "mais de um" in link.note


@pytest.mark.parametrize("text", [
    "", "   ", "oi", "https://example.com/lesserafim/live",
    "https://notweverse.io/lesserafim", "https://weverse.io", "https://weverse.io/",
    "https://weverse.io/more", "https://weverse.io/live",
    "https://shop.weverse.io/lesserafim", "https://account.weverse.io/login",
    "https://weverse.io/lesserafim/moment/66a07e164b56a696ee71c99315ffe27b/post/1-117229444",
    "https://weverse.onelink.me/abcd/1234",
    "https://youtube.com/watch?v=abc",
])
def test_invalid_links_raise_friendly_errors(text):
    with pytest.raises(LinkError) as exc:
        parse_link(text)
    assert str(exc.value)
