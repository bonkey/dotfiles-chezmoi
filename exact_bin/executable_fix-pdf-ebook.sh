#!/usr/bin/env zsh
set -e

for pdf in "$@"; do
  base="${pdf%.pdf}"

  echo "▶ Processing: $pdf"

  echo "  • Step 1: Decrypting PDF (no rasterization)"
  qpdf --decrypt "$pdf" "${base}-step1.pdf"

  echo "  • Step 2: Normalizing structure (disable object streams, uncompress, linearize)"
  qpdf \
    --object-streams=disable \
    --stream-data=uncompress \
    --linearize \
    "${base}-step1.pdf" "${base}-step2.pdf"

  echo "  • Step 3: Rewriting to Kindle-safe PDF 1.4 (preserve text + vectors)"
  gs \
    -sDEVICE=pdfwrite \
    -dCompatibilityLevel=1.4 \
    -dPDFSETTINGS=/ebook \
    -dDetectDuplicateImages=true \
    -dCompressFonts=true \
    -dSubsetFonts=true \
    -dPreserveAnnots=false \
    -dNOPAUSE -dBATCH \
    -sOutputFile="${base}-fixed.pdf" \
    "${base}-step2.pdf"

  echo "  • Cleaning up intermediate files"
  rm "${base}-step1.pdf" "${base}-step2.pdf"

  echo "✔ Done: ${base}-fixed.pdf"
  echo
done