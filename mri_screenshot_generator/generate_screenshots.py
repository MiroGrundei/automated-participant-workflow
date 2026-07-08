"""Create text-free T1 anatomy snapshots from DICOM zip archives.

The workflow is intentionally narrow:
1. inspect a baseline DICOM zip on the network share without extracting it,
2. identify the most likely T1 anatomical series from DICOM headers,
3. extract only that series locally,
4. convert it with dcm2niix,
5. save sagittal/coronal/axial slices as a PNG without labels or IDs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


NETWORK_DICOM_ROOT = (
    Path(os.getenv("STUDY_DICOM_ROOT") or os.getenv("MEMOSLAP_DICOM_ROOT"))
    if os.getenv("STUDY_DICOM_ROOT") or os.getenv("MEMOSLAP_DICOM_ROOT")
    else None
)
DEFAULT_SESSION = "base"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

T1_POSITIVE_PATTERNS = (
    "t1",
    "t1w",
    "mprage",
    "mp-rage",
    "mp rage",
    "anatom",
    "anat",
    "struct",
    "sag",
)

T1_STRONG_PATTERNS = (
    "mprage",
    "mp-rage",
    "t1_mpr",
    "t1w",
)

REJECT_PATTERNS = (
    "bold",
    "resting",
    "fmri",
    "fieldmap",
    "field map",
    "fmap",
    "gre_field",
    "diff",
    "dwi",
    "noddi",
    "sbref",
    "localizer",
    "scout",
    "phoenix",
    "survey",
    "derived",
)


@dataclass
class SeriesCandidate:
    uid: str
    files: list[str] = field(default_factory=list)
    descriptions: set[str] = field(default_factory=set)
    protocols: set[str] = field(default_factory=set)
    sequences: set[str] = field(default_factory=set)
    image_types: set[str] = field(default_factory=set)
    modalities: set[str] = field(default_factory=set)

    @property
    def combined_text(self) -> str:
        parts = (
            list(self.descriptions)
            + list(self.protocols)
            + list(self.sequences)
            + list(self.image_types)
            + list(self.modalities)
        )
        return " ".join(parts).lower()

    def score(self) -> int:
        text = self.combined_text
        score = 0

        has_strong_t1_signal = any(pattern in text for pattern in T1_STRONG_PATTERNS)

        for pattern in T1_POSITIVE_PATTERNS:
            if pattern in text:
                score += 10
        for pattern in T1_STRONG_PATTERNS:
            if pattern in text:
                score += 20
        for pattern in REJECT_PATTERNS:
            if pattern in text and not has_strong_t1_signal:
                score -= 50

        file_count = len(self.files)
        if 120 <= file_count <= 320:
            score += 12
        elif 80 <= file_count < 120 or 320 < file_count <= 420:
            score += 5
        elif file_count < 20 and not has_strong_t1_signal:
            score -= 20

        if "mr" in text:
            score += 2

        return score

    def summary(self) -> str:
        label = first_sorted(self.descriptions) or first_sorted(self.protocols) or self.uid
        return f"{label} ({len(self.files)} files, score {self.score()})"


def first_sorted(values: Iterable[str]) -> str:
    values = sorted(v for v in values if v)
    return values[0] if values else ""


def safe_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\\".join(str(v) for v in value)
    return str(value)


def import_or_fail(module_name: str, install_hint: str):
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"Missing Python package '{module_name}'. Install it with: {install_hint}"
        ) from exc


def network_zip_path(network_root: Path, sub: str, session: str) -> Path:
    raw_ses_folder = f"sub-{sub}_ses-{session}"
    return network_root / f"sub-{sub}" / f"{raw_ses_folder}.zip"


def iter_zip_dicom_headers(zip_path: Path):
    pydicom = import_or_fail("pydicom", "python -m pip install pydicom")
    tags = [
        "SeriesInstanceUID",
        "SeriesDescription",
        "ProtocolName",
        "SequenceName",
        "ImageType",
        "Modality",
    ]

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.file_size == 0:
                continue
            try:
                with zf.open(info) as dicom_file:
                    ds = pydicom.dcmread(
                        dicom_file,
                        stop_before_pixels=True,
                        specific_tags=tags,
                        force=True,
                    )
            except Exception:
                continue

            uid = safe_value(getattr(ds, "SeriesInstanceUID", "")).strip()
            if not uid:
                continue
            yield info.filename, ds


def collect_series(zip_path: Path) -> dict[str, SeriesCandidate]:
    series: dict[str, SeriesCandidate] = {}
    for member_name, ds in iter_zip_dicom_headers(zip_path):
        uid = safe_value(getattr(ds, "SeriesInstanceUID", "")).strip()
        candidate = series.setdefault(uid, SeriesCandidate(uid=uid))
        candidate.files.append(member_name)
        candidate.descriptions.add(safe_value(getattr(ds, "SeriesDescription", "")))
        candidate.protocols.add(safe_value(getattr(ds, "ProtocolName", "")))
        candidate.sequences.add(safe_value(getattr(ds, "SequenceName", "")))
        candidate.image_types.add(safe_value(getattr(ds, "ImageType", "")))
        candidate.modalities.add(safe_value(getattr(ds, "Modality", "")))
    return series


def choose_t1_series(series: dict[str, SeriesCandidate]) -> SeriesCandidate:
    if not series:
        raise RuntimeError("No DICOM series could be read from the zip archive.")

    ranked = sorted(series.values(), key=lambda item: item.score(), reverse=True)
    best = ranked[0]
    if best.score() < 10:
        details = "; ".join(item.summary() for item in ranked[:8])
        raise RuntimeError(f"No convincing T1 series found. Best candidates: {details}")
    return best


def unique_output_path(directory: Path, member_name: str) -> Path:
    raw_name = Path(member_name).name or "dicom"
    clean_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name)
    output_path = directory / clean_name
    if not output_path.exists():
        return output_path

    stem = output_path.stem
    suffix = output_path.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def extract_series(zip_path: Path, candidate: SeriesCandidate, output_dir: Path, force: bool) -> None:
    if output_dir.exists() and force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    existing_files = [path for path in output_dir.iterdir() if path.is_file()]
    if existing_files and not force:
        return

    with zipfile.ZipFile(zip_path) as zf:
        for member_name in candidate.files:
            target = unique_output_path(output_dir, member_name)
            with zf.open(member_name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def resolve_dcm2niix(dcm2niix_arg: Path | None) -> str:
    candidates = []
    if dcm2niix_arg is not None:
        candidates.append(dcm2niix_arg)
    candidates.extend(
        [
            PROJECT_ROOT / "dcm2niix.exe",
            PROJECT_ROOT / "dcm2niix",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    path_hit = shutil.which("dcm2niix")
    if path_hit:
        return path_hit

    requested = f" Requested path was: {dcm2niix_arg}." if dcm2niix_arg else ""
    raise RuntimeError(
        "dcm2niix was not found. Put dcm2niix.exe in the repository root, "
        "pass --dcm2niix C:\\path\\to\\dcm2niix.exe, or add its folder to PATH."
        + requested
    )


def run_dcm2niix(dicom_dir: Path, nifti_dir: Path, force: bool, dcm2niix_arg: Path | None) -> None:
    dcm2niix = resolve_dcm2niix(dcm2niix_arg)
    if not Path(dcm2niix).exists() and shutil.which(dcm2niix) is None:
        raise RuntimeError(
            f"dcm2niix was resolved to '{dcm2niix}', but that executable cannot be found."
        )

    if nifti_dir.exists() and force:
        shutil.rmtree(nifti_dir)
    nifti_dir.mkdir(parents=True, exist_ok=True)

    existing_niftis = list(nifti_dir.glob("*.nii")) + list(nifti_dir.glob("*.nii.gz"))
    if existing_niftis and not force:
        return

    cmd = [
        dcm2niix,
        "-z",
        "y",
        "-i",
        "y",
        "-o",
        str(nifti_dir),
        "-f",
        "%p_%s",
        str(dicom_dir),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "dcm2niix failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def nifti_shape_score(path: Path) -> int:
    nib = import_or_fail("nibabel", "python -m pip install nibabel")
    img = nib.load(str(path))
    shape = img.shape[:3]
    if len(shape) != 3:
        return 0
    return int(shape[0]) * int(shape[1]) * int(shape[2])


def choose_nifti(nifti_dir: Path) -> Path:
    niftis = list(nifti_dir.glob("*.nii.gz")) + list(nifti_dir.glob("*.nii"))
    if not niftis:
        raise RuntimeError(f"No NIfTI files were created in {nifti_dir}")
    return sorted(niftis, key=nifti_shape_score, reverse=True)[0]


def robust_limits(data):
    import numpy as np

    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0, 1
    nonzero = finite[finite > 0]
    source = nonzero if nonzero.size else finite
    low, high = np.percentile(source, [1, 99.5])
    if low == high:
        low, high = float(source.min()), float(source.max())
    if low == high:
        high = low + 1
    return low, high


def default_sagittal_offset(x_size: int) -> int:
    return min(20, max(8, round(x_size * 0.06)))


def clamp_index(value: int, size: int) -> int:
    return min(size - 1, max(0, value))


def save_snapshot(
    nifti_path: Path,
    snapshot_path: Path,
    sagittal_offset: int | None,
    x: int | None,
    y: int | None,
    z: int | None,
    dpi: int,
) -> None:
    nib = import_or_fail("nibabel", "python -m pip install nibabel")
    import_or_fail("matplotlib", "python -m pip install matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    img = nib.as_closest_canonical(nib.load(str(nifti_path)))
    data = np.asarray(img.get_fdata(dtype=np.float32))
    data = np.squeeze(data)
    if data.ndim != 3:
        raise RuntimeError(f"Expected a 3D T1 image, got shape {data.shape}")

    x_mid, y_mid, z_mid = [dim // 2 for dim in data.shape]
    offset = default_sagittal_offset(data.shape[0]) if sagittal_offset is None else sagittal_offset
    sagittal_index = clamp_index(x if x is not None else x_mid + offset, data.shape[0])
    coronal_index = clamp_index(y if y is not None else y_mid, data.shape[1])
    axial_index = clamp_index(z if z is not None else z_mid, data.shape[2])
    slices = [
        np.rot90(data[sagittal_index, :, :]),
        np.rot90(data[:, coronal_index, :]),
        np.rot90(data[:, :, axial_index]),
    ]
    vmin, vmax = robust_limits(data)

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), dpi=dpi)
    for axis, image_slice in zip(axes, slices):
        axis.imshow(image_slice, cmap="gray", vmin=vmin, vmax=vmax, interpolation="lanczos")
        axis.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0, wspace=0.01, hspace=0)
    fig.savefig(snapshot_path, bbox_inches="tight", pad_inches=0, facecolor="black")
    plt.close(fig)


def write_series_report(series: dict[str, SeriesCandidate], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for candidate in sorted(series.values(), key=lambda item: item.score(), reverse=True):
        rows.append(
            {
                "score": candidate.score(),
                "files": len(candidate.files),
                "series_uid": candidate.uid,
                "series_description": first_sorted(candidate.descriptions),
                "protocol_name": first_sorted(candidate.protocols),
                "sequence_name": first_sorted(candidate.sequences),
                "image_type": first_sorted(candidate.image_types),
            }
        )
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def process_subject(args, sub: str) -> dict[str, str]:
    zip_path = network_zip_path(args.network_root, sub, args.session)
    subject_work = args.work_dir / f"sub-{sub}" / f"ses-{args.session}"
    dicom_dir = subject_work / "t1_dicom"
    nifti_dir = subject_work / "t1_nifti"
    snapshot_path = args.snapshot_dir / f"sub-{sub}_T1_snapshot.png"
    series_report = subject_work / "series_report.json"

    if not zip_path.exists():
        raise FileNotFoundError(f"Missing zip archive: {zip_path}")

    series = collect_series(zip_path)
    write_series_report(series, series_report)
    candidate = choose_t1_series(series)

    if args.list_series:
        return {
            "subject": sub,
            "status": "listed",
            "series": candidate.summary(),
            "zip": str(zip_path),
            "dicom_dir": "",
            "nifti_file": "",
            "snapshot": "",
            "message": f"Series report: {series_report}",
        }

    extract_series(zip_path, candidate, dicom_dir, args.force)
    run_dcm2niix(dicom_dir, nifti_dir, args.force, args.dcm2niix)
    nifti_path = choose_nifti(nifti_dir)
    save_snapshot(
        nifti_path,
        snapshot_path,
        args.sagittal_offset,
        args.x,
        args.y,
        args.z,
        args.dpi,
    )

    return {
        "subject": sub,
        "status": "ok",
        "series": candidate.summary(),
        "zip": str(zip_path),
        "dicom_dir": str(dicom_dir),
        "nifti_file": str(nifti_path),
        "snapshot": str(snapshot_path),
        "message": "",
    }


def write_log(rows: list[dict[str, str]], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "subject",
        "status",
        "series",
        "zip",
        "dicom_dir",
        "nifti_file",
        "snapshot",
        "message",
    ]
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract only T1 DICOMs from baseline zip archives and create text-free snapshots."
    )
    parser.add_argument("--subjects", nargs="+", required=True, help="Participant IDs, e.g. 2275 2276")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="DICOM session label. Default: base")
    parser.add_argument(
        "--network-root",
        type=Path,
        default=NETWORK_DICOM_ROOT,
        required=NETWORK_DICOM_ROOT is None,
        help="Root folder containing sub-ID DICOM zip archives. Can also be set with STUDY_DICOM_ROOT.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("work"),
        help="Local working directory for extracted T1 DICOMs and NIfTIs.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=Path("snapshots"),
        help="Output directory for PNG snapshots.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("t1_snapshot_log.csv"),
        help="CSV log path.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate local outputs for each subject.")
    parser.add_argument(
        "--sagittal-offset",
        type=int,
        default=None,
        help=(
            "Voxel offset from the center for the sagittal slice. "
            "Default: automatic right-of-center offset to avoid the midline gap. "
            "Use 0 for exact center or a negative value for the other side."
        ),
    )
    parser.add_argument("--x", type=int, help="Exact voxel index for sagittal slice.")
    parser.add_argument("--y", type=int, help="Exact voxel index for coronal slice.")
    parser.add_argument("--z", type=int, help="Exact voxel index for axial slice.")
    parser.add_argument("--dpi", type=int, default=240, help="PNG export resolution. Default: 240.")
    parser.add_argument(
        "--dcm2niix",
        type=Path,
        help="Optional explicit path to dcm2niix.exe. Defaults to ./dcm2niix.exe, then PATH.",
    )
    parser.add_argument(
        "--list-series",
        action="store_true",
        help="Only inspect zip archives and write series reports; do not extract/convert/snapshot.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows: list[dict[str, str]] = []

    for sub in args.subjects:
        print(f"Processing sub-{sub}...")
        try:
            row = process_subject(args, sub)
            print(f"  {row['status']}: {row['series']}")
        except Exception as exc:
            row = {
                "subject": sub,
                "status": "error",
                "series": "",
                "zip": str(network_zip_path(args.network_root, sub, args.session)),
                "dicom_dir": "",
                "nifti_file": "",
                "snapshot": "",
                "message": str(exc),
            }
            print(f"  error: {exc}", file=sys.stderr)
        rows.append(row)

    write_log(rows, args.log)
    print(f"Log written to {args.log}")
    return 1 if any(row["status"] == "error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
