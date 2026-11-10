from pathlib import Path

from downverse import paths
from downverse.paths import (
    LiveMeta, artist_parts, file_base_name, folder_date, is_official_account, live_folder,
    sanitize_component, sanitize_folder_name, unique_live_folder,
)

TS = 1773576000  # 2026-03-15 12:00:00 UTC


def meta(uploader="채원", community="LE SSERAFIM", slug="lesserafim", ts=TS, title="t", live_id="2-1"):
    return LiveMeta(live_id, title, community, slug, uploader, ts)


def test_group_member_hierarchy(tmp_path):
    p = live_folder(tmp_path, meta(), tz_mode="utc")
    assert p == tmp_path / "Weverse" / "LE SSERAFIM" / "채원" / "2026-03-15"


def test_official_group_account_has_no_member_folder(tmp_path):
    for name in ("LE SSERAFIM", "LE SSERAFIM ", "le sserafim", "lesserafim", "LE_SSERAFIM_official"):
        p = live_folder(tmp_path, meta(uploader=name), tz_mode="utc")
        assert p == tmp_path / "Weverse" / "LE SSERAFIM" / "2026-03-15", name


def test_solo_artist_and_solo_mode(tmp_path):
    solo = meta(uploader="TAEYEON", community="TAEYEON", slug="taeyeon")
    assert live_folder(tmp_path, solo, tz_mode="utc") == tmp_path / "Weverse" / "TAEYEON" / "2026-03-15"
    differently_named = meta(uploader="태연", community="TAEYEON", slug="taeyeon")
    assert artist_parts(differently_named, "auto") == ["TAEYEON", "태연"]
    assert artist_parts(differently_named, "solo") == ["TAEYEON"]


def test_emoji_removed_from_artist_folders_but_kept_in_titles():
    assert artist_parts(meta(uploader="채채🤎")) == ["LE SSERAFIM", "채채"]
    assert file_base_name("행복한 평이루💜", "1") == "행복한 평이루💜"


def test_is_official_account_edge_cases():
    assert is_official_account("", "BTS")
    assert is_official_account("Billlie_official", "Billlie", "billlie")
    assert not is_official_account("Suhyeon", "Billlie", "billlie")


def test_folder_date_timezones():
    assert folder_date(TS, "utc") == "2026-03-15"
    late = TS + 11 * 3600                                    # 23:00 UTC do dia 15 = 08:00 KST do dia 16
    assert folder_date(late, "utc") == "2026-03-15"
    assert folder_date(late, "kst") == "2026-03-16"
    assert folder_date(None) == "Sem data"


def test_sanitize_component():
    assert sanitize_component('a<b>c:d"e/f\\g|h?i*j') == "a b c d e f g h i j"
    assert sanitize_component("  ...  ") == "_"
    assert sanitize_component("CON") == "_CON"
    assert sanitize_component("nul.txt") == "_nul.txt"
    assert sanitize_component("fim com ponto.") == "fim com ponto"
    assert sanitize_component("") == "_"
    long = sanitize_component("가" * 200)
    assert len(long.encode()) <= 180 and long
    assert sanitize_folder_name("🎀") == "_"


def test_unique_folder_numbers_days_with_more_than_one_live(tmp_path):
    owners = {}
    base = tmp_path / "2026-03-15"

    def claim(live_id):
        folder = unique_live_folder(base, live_id, owners.get)
        owners[folder] = live_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "v.mp4").write_bytes(b"x")
        return folder

    a, b, c = claim("a"), claim("b"), claim("c")
    assert [f.name for f in (a, b, c)] == ["2026-03-15", "2026-03-15 (2)", "2026-03-15 (3)"]
    assert claim("b") == b          # a mesma live volta para a mesma pasta
    assert claim("a") == a


def test_unique_folder_avoids_unknown_folder_with_video(tmp_path):
    base = tmp_path / "2026-03-15"
    base.mkdir()
    (base / "outra.mkv").write_bytes(b"x")
    assert unique_live_folder(base, "x", lambda f: None).name == "2026-03-15 (2)"
    (tmp_path / "vazia").mkdir()
    assert unique_live_folder(tmp_path / "vazia", "x", lambda f: None).name == "vazia"


def test_default_videos_dir_reads_xdg_user_dirs(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "user-dirs.dirs").write_text('XDG_VIDEOS_DIR="$HOME/Vídeos"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.delenv("XDG_VIDEOS_DIR", raising=False)
    monkeypatch.setattr(paths.platform, "system", lambda: "Linux")
    assert paths.default_videos_dir() == Path.home() / "Vídeos"
    monkeypatch.setattr(paths.platform, "system", lambda: "Darwin")
    assert paths.default_videos_dir() == Path.home() / "Movies"
