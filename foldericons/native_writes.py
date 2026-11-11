"""Conflict-checked, atomic native-client uploads on local Linux filesystems."""

import ctypes
import os
import secrets
import stat
import threading
import time
from dataclasses import dataclass, field


MAX_CHUNK = 4 * 1024 * 1024
MAX_FILE = 64 * 1024**3
MAX_UPLOADS = 16
UPLOAD_TTL = 900


class WriteError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def revision(info):
    return f"{info.st_dev:x}-{info.st_ino:x}-{info.st_mtime_ns:x}-{info.st_ctime_ns:x}-{info.st_size:x}"


def target_info(parent, name):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise WriteError(409, "The target is not a regular file with a single link.")
    return info


@dataclass
class Upload:
    owner: str
    source: str
    path: str
    name: str
    parent: int
    staging: int
    original: str | None
    length: int = 0
    touched: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def close(self):
        os.close(self.staging)
        os.close(self.parent)


class NativeWrites:
    def __init__(self):
        self.uploads = {}
        self.lock = threading.Lock()

    def _expire_locked(self):
        deadline = time.monotonic() - UPLOAD_TTL
        for key, upload in list(self.uploads.items()):
            if upload.touched < deadline and upload.lock.acquire(blocking=False):
                try:
                    del self.uploads[key]
                    upload.close()
                finally:
                    upload.lock.release()

    def expire(self):
        with self.lock:
            self._expire_locked()

    def begin(self, owner, source, path, parent, name, mode, expected):
        current = target_info(parent, name)
        original = revision(current) if current else None
        if mode == "create" and current is not None:
            raise WriteError(409, "A file with that name already exists.")
        if mode == "edit" and current is None:
            raise WriteError(404, "The file no longer exists.")
        if expected and expected != original:
            raise WriteError(409, "The server copy changed. Reopen the file.")
        with self.lock:
            self._expire_locked()
            if len(self.uploads) >= MAX_UPLOADS:
                raise WriteError(429, "The server is busy with other uploads.")
            try:
                staging = os.open(".", os.O_RDWR | os.O_TMPFILE | os.O_CLOEXEC, 0o600, dir_fd=parent)
            except OSError as error:
                raise WriteError(409, "This storage does not support safe staging for FilePoint writes.") from error
            identifier = secrets.token_hex(24)
            self.uploads[identifier] = Upload(owner, source, path, name, parent, staging, original)
        return {"upload": identifier, "length": current.st_size if current else 0, "revision": original}

    def _acquire(self, identifier, owner):
        with self.lock:
            self._expire_locked()
            upload = self.uploads.get(identifier)
            if upload is None or not secrets.compare_digest(upload.owner, owner):
                raise WriteError(404, "Upload is unavailable.")
            if not upload.lock.acquire(blocking=False):
                raise WriteError(409, "Another request is using this upload.")
            upload.touched = time.monotonic()
            return upload

    def append(self, identifier, owner, offset, data):
        upload = self._acquire(identifier, owner)
        try:
            if offset != upload.length or not 0 < len(data) <= MAX_CHUNK or offset + len(data) > MAX_FILE:
                raise WriteError(409, "The upload chunk is out of sequence or too large.")
            remaining = memoryview(data)
            while remaining:
                written = os.pwrite(upload.staging, remaining, offset)
                if written <= 0:
                    raise OSError("The storage did not accept the upload chunk.")
                remaining = remaining[written:]
                offset += written
            upload.length = offset
            return {"length": offset}
        finally:
            upload.lock.release()

    def commit(self, identifier, owner, length, authorize):
        upload = self._acquire(identifier, owner)
        try:
            if length != upload.length or os.fstat(upload.staging).st_size != length:
                raise WriteError(409, "The server has not received the complete file.")
            os.fsync(upload.staging)
            parent = authorize(upload.source, upload.path, "edit" if upload.original else "create")
            try:
                if not os.path.samestat(os.fstat(parent), os.fstat(upload.parent)):
                    raise WriteError(409, "The destination folder changed during the upload.")
            finally:
                os.close(parent)
            # Serialize native commits. New files also use an atomic no-overwrite link.
            with self.lock:
                current = target_info(upload.parent, upload.name)
                if (revision(current) if current else None) != upload.original:
                    raise WriteError(409, "The server copy changed during the upload.")
                if current:
                    original = os.open(upload.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=upload.parent)
                    try:
                        if revision(os.fstat(original)) != upload.original:
                            raise WriteError(409, "The server copy changed during the upload.")
                        os.fchown(upload.staging, current.st_uid, current.st_gid)
                        os.fchmod(upload.staging, stat.S_IMODE(current.st_mode) & 0o777)
                        for key in os.listxattr(original):
                            if key.startswith("user.") or key == "system.posix_acl_access":
                                os.setxattr(upload.staging, key, os.getxattr(original, key))
                    finally:
                        os.close(original)
                else:
                    os.fchmod(upload.staging, 0o664)
                os.fsync(upload.staging)
                staged = f"/proc/self/fd/{upload.staging}"
                if current is None:
                    os.link(staged, upload.name, dst_dir_fd=upload.parent, follow_symlinks=True)
                else:
                    temporary = ".filepoint-commit-" + identifier
                    os.link(staged, temporary, dst_dir_fd=upload.parent, follow_symlinks=True)
                    try:
                        os.replace(temporary, upload.name, src_dir_fd=upload.parent, dst_dir_fd=upload.parent)
                    finally:
                        try:
                            os.unlink(temporary, dir_fd=upload.parent)
                        except FileNotFoundError:
                            pass
                info = os.fstat(upload.staging)
                os.fsync(upload.parent)
                del self.uploads[identifier]
                upload.close()
                return {"length": info.st_size, "revision": revision(info)}
        finally:
            upload.lock.release()

    def cancel(self, identifier, owner):
        upload = self._acquire(identifier, owner)
        try:
            with self.lock:
                del self.uploads[identifier]
                upload.close()
        finally:
            upload.lock.release()

    def rename(self, parent, name, destination_parent, destination, replace):
        with self.lock:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise WriteError(409, "Only regular files and folders can be renamed.")
            if replace:
                if not stat.S_ISREG(info.st_mode) or target_info(destination_parent, destination) is None:
                    raise WriteError(409, "The replacement target is unavailable.")
                os.replace(name, destination, src_dir_fd=parent, dst_dir_fd=destination_parent)
            else:
                libc = ctypes.CDLL(None, use_errno=True)
                rename = getattr(libc, "renameat2", None)
                if rename is None:
                    raise WriteError(409, "This server does not support non-overwriting renames.")
                result = rename(parent, os.fsencode(name), destination_parent, os.fsencode(destination), 1)
                if result:
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error))
            current = os.stat(destination, dir_fd=destination_parent, follow_symlinks=False)
            return {"length": current.st_size, "revision": revision(current)}
