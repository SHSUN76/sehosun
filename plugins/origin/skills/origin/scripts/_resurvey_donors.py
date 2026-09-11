"""donor manifest 재생성.

`survey_project` 가 만드는 필드(measured / data_shape / graph ...)만 갈아끼우고,
큐레이션 때 손으로 붙인 `archetype` / `curated_from` 는 보존한다.
`measured` 가 달라지면 donor 파일 자체가 바뀐 것이므로 그 사실을 찍어 준다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from originsession import origin_session  # noqa: E402
from survey import survey_project  # noqa: E402

DONORS = Path(__file__).resolve().parents[1] / "donors"

# 손으로 붙인 필드 — 재생성이 지워서는 안 된다.
CURATED_KEYS = ("archetype", "curated_from")


def main() -> int:
    changed = []
    with origin_session() as op:
        for opj in sorted(DONORS.glob("*.opj")):
            path = DONORS / f"{opj.stem}.yaml"
            old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
            try:
                fresh = survey_project(opj, op=op)
            except RuntimeError as e:
                print(f"  SKIP {opj.name}: {e}")
                continue

            merged = {k: old[k] for k in CURATED_KEYS if k in old}
            merged.update(fresh)
            # source 는 survey가 넣지만 manifest 형식엔 없었다 — 형식을 유지한다.
            merged.pop("source", None)

            if old.get("measured") != merged.get("measured"):
                print(f"  !! {opj.stem}: measured drifted")
                for k, v in merged["measured"].items():
                    if (old.get("measured") or {}).get(k) != v:
                        print(f"     {k}: {(old.get('measured') or {}).get(k)} -> {v}")
            if old.get("data_shape") != merged.get("data_shape"):
                changed.append(opj.stem)
                print(f"  {opj.stem}: data_shape {old.get('data_shape')} "
                      f"-> {merged['data_shape']}")

            path.write_text(
                yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
    print(f"\nrewrote {len(list(DONORS.glob('*.yaml')))} manifests; "
          f"data_shape changed for: {changed or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
