#!/usr/bin/env python3

import argparse
import os
import getpass
from pathlib import Path
from supermemory import Supermemory

def main():
    parser = argparse.ArgumentParser(description='Upload files to mem0')
    parser.add_argument('files', nargs='+', help='Files to upload')

    args = parser.parse_args()

    client = Supermemory(
        api_key=os.environ.get("SUPERMEMORY_API_KEY"),
    )

    for file_path in args.files:
        file_size = Path(file_path).stat().st_size
        if file_size > 1024 * 1024:  # 1 MiB
            print(f"Skipped {file_path}, too large")
            continue

        print(f"Adding {file_path}... ", end="", flush=True)
        file_content = Path(file_path).read_text()

        client.memories.add(content=file_content)
        print("added")

if __name__ == "__main__":
    main()
