# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import os
import requests
import sys

from pathlib import Path
from urllib3.util import parse_url
from tempfile import NamedTemporaryFile
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from ..console import console
from ..logger import logger


def _is_chunked(transfer_encoding: str | None) -> bool:
    return False if not transfer_encoding else transfer_encoding == "chunked"


def _get_attachment_filename(content_disposition: str | None) -> str | None:
    if content_disposition and content_disposition.startswith("attachment"):
        _, filename = map(str.strip, content_disposition.split(";"))
        return filename.split("=")[1]
    return None


def _progress_bar() -> Progress:
    return Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "•",
        DownloadColumn(),
        "•",
        TransferSpeedColumn(),
        "•",
        TimeRemainingColumn(),
        console=console._console,
    )


def _download(url: str, dest_dir: Path, progress: Progress, task_id: TaskID) -> Path:
    console.message(f"[b]Downloading[/b] [i]{url}[/i]")

    # use curl user-agent to pass through anti-bot/anti-crawler reverse proxy on some
    # source package repository
    r = requests.get(url, stream=True, headers={"user-agent": "curl"})
    logger.debug(f"response status {r.status_code}")
    r.raise_for_status()

    rh = r.headers
    logger.debug(f"response header: {rh}")
    # content-length might not be present, e.g. while transfer encoding is chunked
    length = rh.get("content-length") or 0
    chunked = _is_chunked(rh.get("transfer-encoding"))
    # if transfer is chunked use default chunk size, 1024 otherwise
    chunk_size = 1024 if not chunked else None

    # url filename and attachment filename may differ, use attachment filename
    # url otherwise
    filename = _get_attachment_filename(rh.get("content-disposition"))
    if not filename:
        filename = Path(parse_url(url).path).name  # type: ignore
    filepath = dest_dir / filename
    progress.update(task_id, filename=filename, total=int(length))

    # Download to a temporary file w/o deletion on close.
    # The temporary file is deleted automatically if context manager exits
    # before normal download termination.
    # Once download is done, temp file is closed and renamed, one can use os.rename
    # safely here as there is no cwd change.
    # Once rename, delete flag is set to False to keep downloaded file on the filesystem.

    # XXX:
    #   `delete_on_close` is a py3.12+ kwargs.
    #   As we still support py3.11, we need to workaround here.
    #   To be removed when python 3.11 support will be dropped.
    #
    #   Changing delete flag inside context manager seems to be not working for windows platform
    #   for python 3.11 (this is okay for linux/macOS)
    kwargs = dict()
    if sys.version_info >= (3, 12):
        kwargs["delete_on_close"] = False
    else:
        kwargs["delete"] = False

    try:
        tmp_file: str = ""
        with NamedTemporaryFile("wb", dir=dest_dir, **kwargs) as f:  # type: ignore
            tmp_file = f.name
            logger.debug(f"downloading to temporary file {f.name}")
            progress.start_task(task_id)

            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)

                # In case of chunked encoding, iter_content might be empty
                if len(chunk) is None:
                    continue

                progress.update(task_id, advance=len(chunk))
            if length == 0:
                progress.update(task_id, total=f.tell())

            f.close()
            os.rename(f.name, filepath)
            # Once renamed to final download name, set delete flag to False and exit context manager
            f.delete = False
    finally:
        if os.path.isfile(tmp_file):
            os.unlink(tmp_file)

    return filepath


def download_file(url: str, dest_dir: Path) -> Path:
    progress = _progress_bar()
    with progress:
        task_id = progress.add_task("download", start=False, filename="")
        return _download(url, dest_dir, progress, task_id)
