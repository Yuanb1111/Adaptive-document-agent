"""Trusted Linux launcher: enforce offline rendering before exec, fail closed.

Executed in a dedicated process group, never in the Streamlit process. Only Unix
domain sockets (LibreOffice's private IPC) are allowed. The policy is inherited
by child processes. This is network isolation, not a filesystem sandbox.
"""

import ctypes
import errno
import os
import socket
import sys


def restrict_network() -> None:
    lib = ctypes.CDLL("libseccomp.so.2")

    class Comparison(ctypes.Structure):
        _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                    ("a", ctypes.c_uint64), ("b", ctypes.c_uint64)]

    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Comparison)]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("Cannot initialize network policy")
    try:
        deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO
        for name in (b"socket", b"socketpair"):
            syscall = lib.seccomp_syscall_resolve_name(name)
            comparison = Comparison(0, 1, socket.AF_UNIX, 0)  # SCMP_CMP_NE
            if syscall < 0 or lib.seccomp_rule_add_array(context, deny, syscall, 1, ctypes.byref(comparison)) != 0:
                raise RuntimeError("Cannot install network policy")
        # Prevent network operations through asynchronous I/O interfaces.
        syscall = lib.seccomp_syscall_resolve_name(b"io_uring_setup")
        if syscall >= 0 and lib.seccomp_rule_add_array(context, deny, syscall, 0, None) != 0:
            raise RuntimeError("Cannot restrict asynchronous I/O")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("Cannot enforce network policy")
    finally:
        lib.seccomp_release(context)


def main() -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (100_000_000, 100_000_000))
        restrict_network()
        if sys.argv[1:] == ["--probe"]:
            for family in (socket.AF_INET, socket.AF_INET6):
                try:
                    sock = socket.socket(family, socket.SOCK_STREAM)
                except OSError as exc:
                    if exc.errno != errno.EPERM:
                        raise
                else:
                    sock.close()
                    raise RuntimeError("Network policy ineffective")
            return
        executable, *args = sys.argv[1:]
        if not os.path.isabs(executable) or not os.path.isfile(executable):
            raise RuntimeError("Invalid renderer executable")
        os.execv(executable, [executable, *args])
    except Exception:
        # Never echo arguments, document text, paths, or environment secrets.
        sys.exit(78)


if __name__ == "__main__":
    main()
