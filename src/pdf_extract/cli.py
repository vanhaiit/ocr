"""Giao diện dòng lệnh: nhận file hoặc thư mục, xuất JSON kèm báo cáo kiểm chứng.

Mã thoát có ý nghĩa để dùng trong CI hoặc pipeline tự động:
  0 = mọi file đều VERIFIED
  1 = có file NEEDS_REVIEW
  2 = có file REJECTED
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import ExtractionStatus
from .pipeline import process_pdf

EXIT_ALL_VERIFIED = 0
EXIT_NEEDS_REVIEW = 1
EXIT_REJECTED = 2


def collect_pdf_paths(target: Path) -> list[Path]:
    """Nhận một file hoặc quét thư mục tìm PDF."""
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*.pdf") if p.is_file())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-extract",
        description="Chuyển PDF có text layer sang JSON, kèm bằng chứng nguồn gốc từng giá trị.",
    )
    parser.add_argument("target", type=Path, help="File PDF hoặc thư mục chứa PDF")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        help="Thư mục ghi file JSON. Không có thì in ra stdout.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Chỉ in bảng tóm tắt trạng thái, không in JSON đầy đủ.",
    )
    return parser


def _print_summary(name: str, result_json: dict) -> None:
    """In tóm tắt các cổng kiểm tra cho mỗi file, RA STDERR.

    Tóm tắt là thông tin cho người đọc, JSON là dữ liệu cho máy. Tách ra hai
    luồng để `pdf-extract file.pdf > out.json` cho ra JSON thuần, pipe được
    trực tiếp vào jq mà không phải lọc bỏ phần tóm tắt.
    """
    verification = result_json["verification"]
    cross = verification.get("cross_verify") or {}
    prov = verification.get("provenance") or {}
    fonts = verification.get("font_audit") or {}
    glyphs = verification.get("glyph_layers") or {}

    # Mỗi engine kèm mốc nó khớp, để thấy ngay tài liệu có lớp chữ trùng hay không.
    engine_summary = ", ".join(
        f"{c['engine']}={c['chars']}({c['baseline']})" for c in cross.get("comparisons", [])
    )

    print(
        f"{result_json['status']:14} | {name}\n"
        f"  loại PDF        : {verification['pdf_class']}\n"
        f"  mẫu             : {result_json['template']}\n"
        f"  font ToUnicode  : {fonts.get('coverage')}\n"
        f"  glyph trùng lọc : {glyphs.get('duplicate_glyphs_removed')}/{glyphs.get('total_glyphs')}"
        f"  | trang trí loại: {glyphs.get('overlay_glyphs_excluded')}\n"
        f"  engine khớp     : {cross.get('char_multiset_match')} ({engine_summary})\n"
        f"  nguồn gốc       : {prov.get('verbatim_values')}/{prov.get('total_values')} nguyên văn",
        file=sys.stderr,
    )
    for error in result_json.get("errors", []):
        print(f"  [!] {error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    paths = collect_pdf_paths(args.target)
    if not paths:
        print(f"Không tìm thấy PDF nào tại {args.target}", file=sys.stderr)
        return EXIT_REJECTED

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = EXIT_ALL_VERIFIED

    for path in paths:
        result = process_pdf(str(path))
        payload = result.to_json()

        if result.status is ExtractionStatus.REJECTED:
            exit_code = EXIT_REJECTED
        elif result.status is ExtractionStatus.NEEDS_REVIEW and exit_code == EXIT_ALL_VERIFIED:
            exit_code = EXIT_NEEDS_REVIEW

        _print_summary(path.name, payload)

        if args.out_dir:
            out_path = args.out_dir / f"{path.stem}.json"
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  -> {out_path}", file=sys.stderr)
        elif not args.summary_only:
            print(json.dumps(payload, ensure_ascii=False, indent=2))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
