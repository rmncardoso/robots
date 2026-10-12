"""The parquet ground truth of a recorded LeRobot dataset on disk.

``meta/episodes/**/*.parquet`` is what a dataset actually recorded, and three
layers ask it the same question: the sim facade
(:meth:`~strands_robots.simulation.base.SimEngine.verify_dataset_episodes`)
confirms a collection run produced the episodes it intended, the
``verify-dataset`` checker gates a dataset before training, and the episode
judge resolves an episode's frame range before it reads a label. So the read
sits below all three rather than inside the checker that first needed it - a
reader that lives above one of its callers is a fact that caller reaches up for,
or copies.

It earns that place by its dependencies: ``pyarrow``, the standard library, and
:func:`~strands_robots.utils.declared_count`, the one owner of "is this header a
count" - and nothing else internal.

``meta/stats.json`` is read here for the same reason. Which control columns are
too flat, or too broken, for mean-std normalization to scale is a fact about the
recorded dataset: the ``verify-dataset`` advice asks it, and so does any trainer
that refuses such a dataset, so :func:`flat_control_columns` answers both rather
than living inside the first and being copied by the second.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from strands_robots.utils import declared_count

#: The dataset-wide ``std`` below which :func:`flat_control_columns` calls a
#: control column near-constant, and the default of ``verify-dataset --min-std``.
#: Mean-std normalization divides by ``std``, so a column this flat has whatever
#: deviation remains scaled by about 1e3. The threshold is in the column's own
#: unit: a milliradian on a radian-valued joint, a thousandth of a degree on a
#: degree-valued one.
NEAR_CONSTANT_STD = 1e-3


def read_dataset_episode_indices(root: str | Path) -> dict[str, Any]:
    """Read episode-level ground truth from a LeRobot v3 dataset on disk.

    Parses every ``meta/episodes/**/*.parquet`` file under ``root`` and returns
    the recorded episode index set plus per-episode frame counts. This is the
    parquet source of truth used by :meth:`~strands_robots.simulation.base.SimEngine.verify_dataset_episodes`
    to confirm a recording session produced the number of distinct episodes the
    caller intended (rather than one merged ``episode_index=0`` mega-episode).

    Pure ``pyarrow`` read - it does NOT import ``lerobot`` or instantiate a
    ``LeRobotDataset`` (which would re-validate/scan the whole dataset). Reads
    only the lightweight episode metadata parquet.

    Args:
        root: Dataset root directory (the dir that contains ``meta/``).

    Returns:
        Dict with:
          - ``episode_indices``: sorted list of distinct ``episode_index`` values.
          - ``total_episodes``: number of distinct episodes (``len`` of above).
          - ``total_frames``: sum of per-episode ``length`` (0 if unavailable).
            A dataset whose episodes all recorded 0 frames also sums to 0, so
            read ``frames_per_episode`` to tell "no lengths" from "no frames".
          - ``frames_per_episode``: per-episode frame counts aligned to
            ``episode_indices``. Empty when no episode carried a usable
            ``length`` (the column is absent, or every value is null); a
            recorded ``0`` is a frame count and is reported as one.
          - ``info_total_episodes``: the ``total_episodes`` recorded in
            ``meta/info.json`` (``None`` if that file is absent or unreadable, or
            if it declares no usable count - see ``info_problems``). Returned
            alongside the parquet truth so callers can cross-check the two
            metadata sources for agreement - a healthy dataset has
            ``info_total_episodes == total_episodes``.
          - ``info_problems``: one message per ``meta/info.json`` declaration
            that is present but is not a count (empty list for a healthy
            dataset). A cross-check must fail on these rather than read the
            ``None`` count as an absent header, which is agreement.
          - ``unreadable_files``: ``"<path relative to root>: <error>"`` for
            every ``meta/episodes`` parquet that could not be read (empty list
            for a healthy dataset). A partially-corrupt dataset - one truncated
            file out of twenty, the usual outcome of an interrupted sync or hub
            download - still yields the episode truth of the readable files, so
            callers can localise the damage instead of seeing zero episodes.
            The episode counts above cover ONLY the readable files, so any
            non-empty ``unreadable_files`` means the totals are a lower bound
            and the dataset must not be certified as complete.

    Raises:
        ImportError: If ``pyarrow`` is not installed.
        FileNotFoundError: If ``root`` does not exist (a typo or a dangling
            symlink), or if no ``meta/episodes`` parquet exists under it (no
            episode was ever flushed - the dataset is empty/unfinalized).
        NotADirectoryError: If ``root`` is a file rather than the dataset folder.
        ValueError: If every ``meta/episodes`` parquet is unreadable, so there
            is no episode ground truth at all. The message lists each file and
            its read error.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - pyarrow ships with lerobot
        raise ImportError("read_dataset_episode_indices requires pyarrow (installed with the lerobot extra).") from e

    root_path = Path(root)
    # A wrong path must not reach the "never finalized" message below: that
    # advice sends the caller to a recorder that was never broken.
    # ``exists()`` follows symlinks, so a dangling link reads as missing.
    if not root_path.exists():
        raise FileNotFoundError(f"Dataset root {root_path} does not exist. Check the path for a typo.")
    if not root_path.is_dir():
        raise NotADirectoryError(
            f"Dataset root {root_path} is not a directory. Pass the dataset folder, not a file inside it."
        )
    parquet_files = sorted((root_path / "meta" / "episodes").glob("**/*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(
            f"No meta/episodes parquet under {root_path}. The dataset is empty or was "
            "never finalized (episodes are flushed to parquet at stop_recording/finalize)."
        )

    pairs: list[tuple[int, int]] = []
    seen: set[int] = set()
    unreadable_files: list[str] = []
    readable_files = 0
    saw_length = False
    for pf in parquet_files:
        # A corrupt / truncated / foreign parquet raises ArrowInvalid (a
        # ValueError subclass); an unreadable one raises OSError. Damage is
        # usually confined to a few files (interrupted rsync, partial hub
        # download), so record which file failed and keep reading the rest -
        # aborting the whole read here would report zero episodes for a dataset
        # that is mostly intact and hide which file is actually broken.
        try:
            table = pq.read_table(pf)
        except (ValueError, OSError) as e:
            unreadable_files.append(f"{pf.relative_to(root_path)}: {e}")
            continue
        readable_files += 1
        cols = table.column_names
        if "episode_index" not in cols:
            continue
        data = table.to_pydict()
        ep_indices = data["episode_index"]
        lengths = data.get("length")
        for i, ep in enumerate(ep_indices):
            ep_int = int(ep)
            if ep_int in seen:
                continue
            seen.add(ep_int)
            recorded = lengths[i] if lengths is not None else None
            saw_length = saw_length or recorded is not None
            length = int(recorded) if recorded is not None else 0
            pairs.append((ep_int, length))

    if unreadable_files and readable_files == 0:
        # Nothing readable at all: there is no ground truth to return, so this
        # is a hard read failure rather than a partial one.
        detail = "; ".join(unreadable_files)
        raise ValueError(f"No readable meta/episodes parquet under {root_path}: {detail}")

    pairs.sort(key=lambda p: p[0])
    episode_indices = [p[0] for p in pairs]
    frames_per_episode = [p[1] for p in pairs]
    # Availability is whether a length was READ, not whether one was positive.
    # A recorded 0 is a frame count - it is the zero-length episode
    # verify_dataset's check 2 exists to flag - so scoring availability as
    # ``any(f > 0 ...)`` reported the dataset whose every episode is empty as
    # the dataset that carries no lengths at all, and that check reads an empty
    # list as "nothing to compare" and does not run. The report was therefore
    # non-monotonic in the damage: ``[5, 0, 0]`` named its two empty episodes
    # while ``[0, 0, 0]`` passed. A column that is present but wholly null
    # stays unavailable - a null length is unknown, not zero.

    # Read meta/info.json total_episodes as a second, independent metadata
    # source. A healthy LeRobot dataset has info.json.total_episodes equal to
    # the distinct episode count in the parquet; a mismatch means the dataset
    # is internally inconsistent (e.g. an interrupted finalize), which
    # verify_dataset_episodes surfaces. Absent/corrupt info.json -> None (the
    # parquet remains the ground truth and is still reported).
    # The declared count is graded by its one owner (``declared_count``) rather
    # than coerced here. A header that declares something which is NOT a count is
    # a third outcome, distinct from both a matching count and an absent header,
    # so it is reported in ``info_problems`` instead of collapsing into the
    # absent case - which a cross-check reads as agreement, the parquet being the
    # sole truth then. Coercing instead was silently destructive both ways:
    # ``int(2.5)`` is ``2``, the very count a two-episode parquet holds, and
    # ``int(1e400)`` raises ``OverflowError`` out of this documented "unknown".
    info_total_episodes: int | None = None
    info_problems: list[str] = []
    info_path = root_path / "meta" / "info.json"
    if info_path.is_file():
        try:
            with info_path.open(encoding="utf-8") as f:
                raw_total = json.load(f)["total_episodes"]
        except (OSError, ValueError, KeyError, TypeError):
            # Absent key, or a file no reader can parse: the documented unknown,
            # indistinguishable from an absent header, and reported by
            # verify_dataset's own meta/info.json check.
            pass
        else:
            info_total_episodes = declared_count(raw_total)
            if info_total_episodes is None:
                info_problems.append(f"meta/info.json total_episodes={raw_total!r} is not an episode count")

    return {
        "episode_indices": episode_indices,
        "total_episodes": len(episode_indices),
        "total_frames": sum(frames_per_episode) if saw_length else 0,
        "frames_per_episode": frames_per_episode if saw_length else [],
        "info_total_episodes": info_total_episodes,
        "info_problems": info_problems,
        "unreadable_files": unreadable_files,
    }


def _is_control_feature(name: str) -> bool:
    """Whether ``name`` is a control feature: ``action`` or an ``observation.state*``.

    ``verify-dataset``'s dead-column check and :func:`flat_control_columns` both
    grade exactly these features.
    """
    return name == "action" or name == "observation.state" or name.startswith("observation.state.")


def flat_control_columns(root: str | Path, min_std: float = NEAR_CONSTANT_STD) -> dict[str, list[tuple[str, str]]]:
    """The control columns mean-std normalization cannot scale, each with its reason.

    Reads ``meta/stats.json``, the dataset-wide stats a normalizer divides by,
    and flags every ``action`` / ``observation.state*`` column whose ``std`` is
    below ``min_std`` (near-constant) or is nan or infinite. Per-episode stats
    cannot answer this: a column held still within each episode and moved
    between them has a healthy dataset-wide spread. A nested (2-D) ``std``, such
    as a matrix-valued feature's, is skipped: only a flat list of numbers is
    graded. It never raises on what the file holds, so a checker or a preflight
    whose contract is to report can call it as is.

    Args:
        root: Dataset root directory (the dir that contains ``meta/``).
        min_std: The spread every column is expected to reach; a positive finite
            number, which the caller grades. Defaults to :data:`NEAR_CONSTANT_STD`.

    Returns:
        ``{feature: [(column, reason), ...]}`` for each control feature with a
        flagged column, in file order. ``column`` is ``"[<index>]"``, and
        ``reason`` is ``"std is <value>"`` (``"std is 0.0"``, ``"std is nan"``).
        Empty when ``meta/stats.json`` is absent, unreadable or not an object;
        an entry that is not a real number (a nested or ``bool`` stat) is never
        flagged.
    """
    try:
        stats = json.loads((Path(root) / "meta" / "stats.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stats, dict):
        return {}

    flagged: dict[str, list[tuple[str, str]]] = {}
    for feat, values in stats.items():
        stds = values.get("std") if _is_control_feature(feat) and isinstance(values, dict) else None
        if not isinstance(stds, list):
            continue
        # ``nan < min_std`` is False, so a non-finite float is named by its own
        # test. Only a float can be one: ``math.isfinite`` raises on an integer
        # too large for a float, which ``json`` parses from a long literal.
        columns = [
            (f"[{j}]", f"std is {std}")
            for j, std in enumerate(stds)
            if isinstance(std, (int, float))
            and not isinstance(std, bool)
            and (std < min_std or isinstance(std, float) and not math.isfinite(std))
        ]
        if columns:
            flagged[feat] = columns
    return flagged
