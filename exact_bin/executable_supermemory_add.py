#!/usr/bin/env python3

import argparse
from pathlib import Path
from supermemory import Supermemory

def main():
    parser = argparse.ArgumentParser(description='Upload files to Supermemory')
    parser.add_argument('files', nargs='+', help='Files to upload')

    args = parser.parse_args()

    client = Supermemory()

    for file_path in args.files:
        client.memories.upload_file(
            file=Path(file_path),
        )

if __name__ == "__main__":
    main()
