"""The two Unitree G1 entries describe the two models the menagerie ships.

The ``unitree_g1`` entry loads ``g1.xml``, whose body tree ends at the wrists -
``changelog.d/2899-humanoid-camera-mount-recipe.md`` measured that while
documenting a camera mount - yet its description read "29-DOF + dexterous
hands". A reader sizing an action vector from the catalog therefore expected
fingers that the asset has no joints for, and the ``joints`` figure beside the
claim said 29, so the entry contradicted itself.

The hands are in a second model in the same upstream directory,
``g1_with_hands.xml``: the same 29 body joints plus :data:`HAND_JOINTS`, seven
per hand. It has its own entry here rather than a note in the prose, because an
entry is what ``Robot(name)`` resolves, what the asset resolver downloads and
what the catalog cards and the viewer read - nothing else reaches all four.

The asset is fetched, never vendored. Both entries name one
``robot_descriptions`` module, and that module's ``PACKAGE_PATH`` is the whole
upstream directory, so the second model arrives with the first through the
mechanism already in the tree (``strands_robots/assets/download.py``) and no
third-party file is copied into this repository.

Everything here is graded from ``robots.json`` and ``docs/hooks/`` alone, so it
holds on any install: no MuJoCo, no downloaded assets, no network. The claims
that need the compiled models live in
``tests/simulation/test_g1_asset_variants_differ_by_their_hand_joints.py``,
because ``tests/registry`` repoints ``STRANDS_ASSETS_DIR`` at a per-test temp
dir where no asset is ever present.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests._docs_hooks import docs_hook

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROBOTS_JSON = REPO_ROOT / "strands_robots" / "registry" / "robots.json"

#: The hand joints ``g1_with_hands.xml`` adds, in the order the asset declares
#: them: three thumb, two middle and two index hinges per hand.
HAND_JOINTS: tuple[str, ...] = (
    "left_hand_thumb_0_joint",
    "left_hand_thumb_1_joint",
    "left_hand_thumb_2_joint",
    "left_hand_middle_0_joint",
    "left_hand_middle_1_joint",
    "left_hand_index_0_joint",
    "left_hand_index_1_joint",
    "right_hand_thumb_0_joint",
    "right_hand_thumb_1_joint",
    "right_hand_thumb_2_joint",
    "right_hand_middle_0_joint",
    "right_hand_middle_1_joint",
    "right_hand_index_0_joint",
    "right_hand_index_1_joint",
)

#: The joints both models share: the figure ``unitree_g1`` declares.
BODY_JOINTS = 29

#: One floating base joint per model: reported as ``base`` by
#: ``get_robot_state``, so counted neither by ``joints`` nor by a description.
FLOATING_BASE_JOINTS = 1

#: The upstream directory both models live in - the menagerie path, which is
#: NOT either entry's asset cache dir for the robot with hands.
MENAGERIE_DIR = "unitree_g1"


def _entries() -> dict[str, dict]:
    return json.loads(ROBOTS_JSON.read_text(encoding="utf-8"))["robots"]


def _entry(name: str = "unitree_g1_with_hands") -> dict:
    return _entries()[name]


class TestTheEntryIsWellFormed:
    """Graded from ``robots.json`` alone, so it holds with no MuJoCo installed."""

    def test_the_registry_declares_the_robot(self) -> None:
        entry = _entry()
        assert entry["category"] == "humanoid"
        assert "G1" in entry["description"]
        assert "hands" in entry["description"]

    def test_the_declared_count_is_the_body_plus_the_hands(self) -> None:
        """43: the joints the simulation reports; the free base is not one of them."""
        entry = _entry()
        assert entry["joints"] == BODY_JOINTS + len(HAND_JOINTS) == 43
        assert entry["joints"] + FLOATING_BASE_JOINTS == 44, "the model's njnt, for the record"

    def test_the_description_carries_the_dof_a_reader_sizes_an_action_vector_from(self) -> None:
        """Both figures, because the hands are the reason to pick this entry over the other."""
        description = _entry()["description"]
        assert f"{BODY_JOINTS + len(HAND_JOINTS)}-DOF" in description
        assert str(BODY_JOINTS) in description and str(len(HAND_JOINTS) // 2) in description

    def test_the_asset_names_the_with_hands_model_and_its_own_scene(self) -> None:
        """The scene wrapper matters: it is what ``add_robot`` loads for a floor and lights."""
        asset = _entry()["asset"]
        assert asset["model_xml"] == "g1_with_hands.xml"
        assert asset["scene_xml"] == "scene_with_hands.xml"

    def test_the_declared_alias_resolves_to_the_robot(self) -> None:
        from strands_robots.registry import resolve_name

        aliases = _entry()["aliases"]
        assert aliases, "the entry advertises alternative spellings"
        assert "unitree_g1_with_hands" not in aliases, "a self-alias makes every registry read raise"
        for alias in aliases:
            assert resolve_name(alias) == "unitree_g1_with_hands"


class TestTheHandLessEntryNoLongerPromisesHands:
    """The other half of the change: ``unitree_g1`` describes ``g1.xml``."""

    def test_the_description_claims_no_hands(self) -> None:
        """The asset has no finger joint, so the catalog must not advertise one."""
        entry = _entries()["unitree_g1"]
        assert entry["asset"]["model_xml"] == "g1.xml", "premise: this entry loads the hand-less model"
        assert "hand" not in entry["description"].lower(), entry["description"]

    def test_the_two_entries_are_told_apart_by_their_joint_count(self) -> None:
        """The figure is the one discovery surface that separates them at a glance."""
        assert _entries()["unitree_g1"]["joints"] == BODY_JOINTS
        assert _entry()["joints"] > _entries()["unitree_g1"]["joints"]


class TestTheAssetIsFetchedAndNotVendored:
    """The second model arrives through the resolver, so no upstream file is copied in."""

    def test_both_entries_name_one_robot_descriptions_module(self) -> None:
        """One module, one download: its ``PACKAGE_PATH`` is the directory holding both models."""
        assert _entry()["asset"]["robot_descriptions_module"] == "g1_mj_description"
        assert _entries()["unitree_g1"]["asset"]["robot_descriptions_module"] == "g1_mj_description"

    def test_the_resolver_reads_the_declared_module_rather_than_guessing_one(self) -> None:
        """The naming heuristic would look for ``unitree_g1_with_hands_mj_description``, which does not exist.

        It answers with a warning and a fall-through, not a refusal, so a missing
        declaration would leave the robot quietly unfetchable. Reading the field
        back through the resolver costs no import: an explicit entry returns
        before any candidate is tried.
        """
        from strands_robots.assets.download import _resolve_robot_descriptions_module

        entry = _entry()
        assert _resolve_robot_descriptions_module("unitree_g1_with_hands", entry) == "g1_mj_description"

    def test_the_cache_dir_is_the_entrys_own_and_not_the_upstream_path(self) -> None:
        """Two entries may not share an asset dir, so this one cannot be the menagerie's.

        ``tests/registry/test_integrity.py::test_asset_dirs_are_unique`` is that
        rule. The dir is the cache directory the resolver symlinks at the
        description's ``PACKAGE_PATH``, so naming it after the entry costs
        nothing on disk. The two places that read it as an UPSTREAM path need
        the menagerie's name instead: the docs manifest gets it from the row
        :class:`TestTheCatalogStreamsItFromTheUpstreamDirectory` pins, and the
        downloader's git fallback does not, so that path cannot fetch this entry.
        """
        assert _entry()["asset"]["dir"] == "unitree_g1_with_hands"
        assert _entry()["asset"]["dir"] != _entries()["unitree_g1"]["asset"]["dir"]


class TestTheCatalogStreamsItFromTheUpstreamDirectory:
    """``docs/hooks/manifest.py`` sends the browser at a URL, and a wrong one 404s silently.

    The manifest builds a menagerie robot's URL from its asset ``dir``, which
    here is this repository's cache name rather than an upstream path. The
    hook's ``_DESCRIPTION_REPOS`` table is its existing answer for that case
    (``aliengo``, ``unitree_h1_2`` and seven more), and a row there also fixes the
    "Model:" link on the generated page, which ``robot_pages.py`` reads from the
    same manifest entry.
    """

    def test_the_row_points_at_the_directory_the_other_g1_is_served_from(self) -> None:
        hook = docs_hook("manifest")
        repo, ref, subdir = hook._DESCRIPTION_REPOS["unitree_g1_with_hands"]
        assert repo == "google-deepmind/mujoco_menagerie"
        assert subdir == MENAGERIE_DIR == _entries()["unitree_g1"]["asset"]["dir"]
        assert ref == hook.MENAGERIE_REF, "a second pin for one repository would drift"

    def test_the_viewer_loads_the_with_hands_model_from_that_directory(self) -> None:
        """The pair the viewer needs: the shared directory, and the files inside it."""
        robots = docs_hook("manifest").build_manifest()["robots"]
        entry, hand_less = robots["unitree_g1_with_hands"], robots["unitree_g1"]
        assert entry["base_url"] == hand_less["base_url"]
        assert entry["model"] == "g1_with_hands.xml"
        assert entry["scene"] == "scene_with_hands.xml"
        assert entry["viewer"] is True
