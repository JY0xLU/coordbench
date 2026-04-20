import csv
import json
import zipfile
from pathlib import Path

import pandas as pd

from coordbench.dataset.prepare import _extract_prompt_from_raw, prepare_human_panels
from coordbench.dataset.profile import profile_dataset


def _write_docx(path: Path, lines: list[str]) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    )
    for line in lines:
        xml += f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>"
    xml += "</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _study1_fixture(path: Path) -> None:
    header = ["n", "condition "] + [f"op{i}" for i in range(1, 31)]
    prompt_row = ["", ""] + [f"Name a city:" if i == 1 else f"Name a mountain:" if i == 2 else "" for i in range(1, 31)]
    british = ["1", "British"] + ["london", "everest"] + [""] * 28
    global_row = ["2", "Global"] + ["paris", "alps"] + [""] * 28
    _write_csv(path, header, [prompt_row, british, global_row])


def _study2_fixture(path: Path) -> None:
    header = ["ResponseId", "country_cat"] + [f"item_{i}_sa" for i in range(1, 16)] + [f"item_{i}_uk" for i in range(1, 16)]
    prompt_row = ["", ""] + [f"1.nameacity" if i == 1 else f"2.nameamountain" if i == 2 else "" for i in range(1, 16)] + [f"1.nameacity" if i == 1 else f"2.nameamountain" if i == 2 else "" for i in range(1, 16)]
    import_row = ["", ""] + ["meta"] * 30
    british = ["resp_brit", "british"] + ["cape town", "table mountain"] + [""] * 13 + ["london", "everest"] + [""] * 13
    sa = ["resp_sa", "south african"] + ["johannesburg", "drakensberg"] + [""] * 13 + ["london", "everest"] + [""] * 13
    _write_csv(path, header, [prompt_row, import_row, british, sa])


def _study3_fixture(path: Path) -> None:
    header = ["ResponseId", "Country"] + [f"item_{i}" for i in range(1, 16)] + [f"item_{i}_glo" for i in range(1, 16)]
    prompt_row = ["", ""] + [f"1.nameacity" if i == 1 else f"2.nameamountain" if i == 2 else "" for i in range(1, 16)] + [f"1.nameacity" if i == 1 else f"2.nameamountain" if i == 2 else "" for i in range(1, 16)]
    import_row = ["", ""] + ["meta"] * 30
    chile = ["resp_chi", "chile"] + ["santiago", "andes"] + [""] * 13 + ["new york", "everest"] + [""] * 13
    sa = ["resp_sa3", "south_african"] + ["johannesburg", "drakensberg"] + [""] * 13 + ["london", "everest"] + [""] * 13
    _write_csv(path, header, [prompt_row, import_row, chile, sa])


def test_prepare_and_profile_pipeline(tmp_path: Path):
    source_dir = tmp_path / "source" / "osf_fv47d" / "unit_snapshot"
    datasets_dir = source_dir / "datasets"
    materials_dir = source_dir / "materials"
    datasets_dir.mkdir(parents=True)
    materials_dir.mkdir(parents=True)

    _write_docx(
        materials_dir / "Table_of_Alignment_Items.docx",
        [
            "1",
            "Name a city",
            "2",
            "Name a mountain",
        ],
    )
    _study1_fixture(datasets_dir / "Study1.csv")
    _study2_fixture(datasets_dir / "Study2.csv")
    _study3_fixture(datasets_dir / "Study3.csv")
    (datasets_dir / "Study1b.csv").write_text("", encoding="utf-8")
    (datasets_dir / "Study1c.xlsx").write_bytes(b"")
    (materials_dir / "Instructions_International_Alignment_Study.docx").write_bytes(b"")
    (materials_dir / "Supplementary_Materials.docx").write_bytes(b"")
    (materials_dir / "RScriptForInternationalAlignmentPaper.html").write_text("", encoding="utf-8")
    (materials_dir / "Leave_One_Out_Bootstrapping.html").write_text("", encoding="utf-8")
    (source_dir / "source_manifest.json").write_text(json.dumps({"snapshot_id": "unit_snapshot"}), encoding="utf-8")

    prepared_root = tmp_path / "prepared"
    prepared_dir = prepare_human_panels(source_dir, output_root=prepared_root)
    participant = pd.read_csv(prepared_dir / "participant_responses.csv")
    assert "study2_british_within" in participant["panel_id"].unique()
    assert "study3_chilean_between" in participant["panel_id"].unique()

    profiled_dir = profile_dataset(prepared_dir)
    manifest = json.loads((profiled_dir / "benchmark_manifest.json").read_text(encoding="utf-8"))
    assert manifest["default_panel_id"] == "study2_british_within"
    assert (profiled_dir / "selection_report.md").exists()


def test_extract_prompt_from_raw_prefers_specific_aliases():
    item_table = {
        8: "Name a city",
        11: "Name a sport player (any sport",
        15: "Name a television broadcasting organisation",
        27: "Name a typical dish",
        28: "Name a typical flower",
        29: "Name a sport",
    }

    assert _extract_prompt_from_raw("2.nameasportplayer", item_table, 2) == "Name a sport player (any sport)"
    assert _extract_prompt_from_raw("6.nameadish", item_table, 6) == "Name a typical dish"
    assert _extract_prompt_from_raw("10.nameatvbroadcastorganisation", item_table, 10) == (
        "Name a television broadcasting organisation"
    )
    assert _extract_prompt_from_raw("14.nameaflower", item_table, 14) == "Name a typical flower"
