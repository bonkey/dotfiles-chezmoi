#!/usr/bin/env python

import os
import re
import shutil
import sys
from pathlib import Path
from ebooklib import epub
from bs4 import BeautifulSoup
import argparse

def clean_title(file_name):
    # Remove unwanted characters and format to title case
    title = re.sub(r'[_\W]+', ' ', file_name).strip()
    return title.title()

def extract_metadata(epub_path):
    try:
        book = epub.read_epub(epub_path)
        title, author = None, None

        # Extract metadata from the EPUB file
        for item in book.get_metadata('DC', 'title'):
            title = item[0]
        for item in book.get_metadata('DC', 'creator'):
            author = item[0]

        return title, author
    except Exception as e:
        print(f"Error reading EPUB metadata: {e}")
        return None, None

def organize_files(directory, dry_run=False):
    file_groups = {}
    path = Path(directory)

    # Group files by their base name
    for file in path.glob('*.*'):
        if file.is_file():
            if file.name == '.DS_Store':
                continue

            base_name = file.stem
            if base_name not in file_groups:
                file_groups[base_name] = []
            file_groups[base_name].append(file)

    # Process each group of files
    for base_name, files in file_groups.items():
        epub_file = next((f for f in files if f.suffix.lower() == '.epub'), None)
        new_folder_name = clean_title(base_name)
        new_title_name = new_folder_name
        folder = path / new_folder_name

        # Attempt to extract title and author from the EPUB file if available
        if epub_file:
            title, author = extract_metadata(epub_file)
            if title and author:
                title_path = Path(title.title())

                if author and len(author.split()) > 4:
                    new_folder_name = title_path
                    new_title_name = title_path
                    folder = path / new_folder_name
                else:
                    author_path = Path(author.title())
                    new_folder_name = author_path / title_path
                    new_title_name = title_path
                    folder = path / new_folder_name

        # Create the folder path
        if not dry_run:
            folder.mkdir(parents=True,exist_ok=True)

        for file in files:
            # Define the new name for all files based on metadata or cleaned name
            new_name = f"{new_title_name}{file.suffix.lower()}"
            new_path = folder / new_name

            # Show the intended action
            print(f"{file} -> {new_path}")

            # Move and rename the file if not in dry-run mode
            if not dry_run:
                shutil.move(str(file), new_path)

def main():
    parser = argparse.ArgumentParser(description="Organize ebook files by grouping, renaming based on EPUB metadata, and placing them in the same folder.")
    parser.add_argument('directory', nargs='?', help='Path to the directory containing ebook files')
    parser.add_argument('--dry-run', action='store_true', help='Show the renaming actions without applying them')
    args = parser.parse_args()

    if not args.directory:
        print("Usage: python organize_ebooks.py <directory_path> [--dry-run]")
        sys.exit(1)

    organize_files(args.directory, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
