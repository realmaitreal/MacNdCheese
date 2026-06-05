#!/usr/bin/env python3
"""
apply.py — Apply msync (Mach semaphore) patch to Wine Staging 11.9 source.

Based on CrossOver's msync implementation (Copyright CodeWeavers / Marc-Aurel Zent).
Adapted by the MacNCheese project for Wine Staging 11.9.

Usage:
    cd /path/to/wine-staging-11.9-source
    python3 /path/to/patches/msync/apply.py

The script is idempotent: running it twice is safe.
"""

import os
import sys
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# ── helpers ────────────────────────────────────────────────────────────────

def read(path):
    with open(path, "r") as f:
        return f.read()

def write(path, content):
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {path}")

def insert_after(text, needle, insertion):
    """Insert `insertion` after the first occurrence of `needle` in `text`."""
    idx = text.find(needle)
    if idx == -1:
        return None  # not found
    end = idx + len(needle)
    return text[:end] + insertion + text[end:]

def insert_before(text, needle, insertion):
    """Insert `insertion` before the first occurrence of `needle` in `text`."""
    idx = text.find(needle)
    if idx == -1:
        return None
    return text[:idx] + insertion + text[idx:]

def replace_first(text, old, new):
    if old not in text:
        return None
    return text.replace(old, new, 1)

def patch_file(path, fn):
    """Apply fn(content) -> new_content to file at path.  fn returns None to signal 'already patched / skip'."""
    content = read(path)
    result = fn(content)
    if result is None or result == content:
        print(f"  skip  {path}  (already patched or marker not found)")
        return
    write(path, result)


# ── guard ──────────────────────────────────────────────────────────────────

def check_wine_root():
    for name in ("server/main.c", "dlls/ntdll/Makefile.in", "configure.ac"):
        if not os.path.exists(name):
            sys.exit(f"ERROR: Run this script from the root of a Wine source tree.\n"
                     f"       Missing: {name}")

# ── copy new files ─────────────────────────────────────────────────────────

def copy_new_files():
    # (src, dst, always_overwrite)
    # inproc_sync.c must always be replaced: vanilla Wine 11.9 has only the
    # Linux ntsync + stubs version; we need the CrossOver version that adds the
    # #elif __APPLE__ msync section.
    copies = [
        (os.path.join(HERE, "server/msync.c"),       "server/msync.c",             False),
        (os.path.join(HERE, "server/msync.h"),       "server/msync.h",             False),
        (os.path.join(HERE, "server/inproc_sync.c"), "server/inproc_sync.c",       True),
        (os.path.join(HERE, "ntdll/msync.c"),        "dlls/ntdll/unix/msync.c",    False),
        (os.path.join(HERE, "ntdll/msync.h"),        "dlls/ntdll/unix/msync.h",    False),
    ]
    for src, dst, overwrite in copies:
        if os.path.exists(dst) and not overwrite:
            print(f"  exists {dst}")
        else:
            shutil.copy2(src, dst)
            print(f"  copy   {dst}")

# ── server/Makefile.in ─────────────────────────────────────────────────────

def patch_server_makefile(c):
    if "msync.c" in c:
        return None
    # inproc_sync.c is already present in vanilla Wine 11.9; only add it when missing
    has_inproc = "inproc_sync.c" in c
    insertion = "\tmsync.c \\\n" if has_inproc else "\tmsync.c \\\n\tinproc_sync.c \\\n"
    # Anchors include the leading tab so insert_before preserves indentation
    for anchor in ("\tmach.c \\\n", "\tmain.c \\\n", "mach.c \\\n", "main.c \\\n"):
        result = insert_before(c, anchor, insertion)
        if result:
            return result
    # Last resort: prepend after SOURCES = \
    return insert_after(c, "SOURCES = \\\n", insertion)

# ── server/main.c ──────────────────────────────────────────────────────────

def patch_server_main(c):
    orig = c

    # Add include
    if '#include "msync.h"' not in c:
        result = insert_after(c, '#include "request.h"\n', '#include "msync.h"\n')
        if result is None:
            print("  WARN: could not find request.h include in server/main.c")
        else:
            c = result

    # Add msync_init_shm() before open_master_socket()
    if "msync_init_shm" not in c:
        result = insert_before(c, "open_master_socket()", "msync_init_shm();\n    ")
        if result is None:
            print("  WARN: could not find open_master_socket() in server/main.c")
        else:
            c = result

    # Add msync_init() after open_master_socket();
    if "msync_init()" not in c:
        result = insert_after(c, "open_master_socket();\n", "    msync_init();\n")
        if result is None:
            print("  WARN: could not find open_master_socket(); in server/main.c")
        else:
            c = result

    return c if c != orig else None

# ── dlls/ntdll/Makefile.in ─────────────────────────────────────────────────

def patch_ntdll_makefile(c):
    if "unix/msync.c" in c:
        return None
    # Add after unix/esync.c or unix/loader.c
    for anchor in ("unix/esync.c \\\n", "unix/loader.c \\\n", "unix/file.c \\\n"):
        result = insert_after(c, anchor, "\tunix/msync.c \\\n")
        if result:
            return result
    print("  WARN: could not find anchor in dlls/ntdll/Makefile.in")
    return None

# ── dlls/ntdll/unix/loader.c ───────────────────────────────────────────────

def patch_loader(c):
    orig = c

    if '#include "msync.h"' not in c:
        result = insert_after(c, '#include "esync.h"\n', '#include "msync.h"\n')
        if result is None:
            result = insert_after(c, '#include "unix_private.h"\n', '#include "msync.h"\n')
        if result:
            c = result
        else:
            print("  WARN: could not insert msync.h include in loader.c")

    if "msync_init()" not in c:
        for anchor in ("esync_init();\n", "startup_info_size = server_init_process();\n"):
            result = insert_after(c, anchor, "    msync_init();\n")
            if result:
                c = result
                break
        else:
            print("  WARN: could not insert msync_init() call in loader.c")

    return c if c != orig else None

# ── dlls/ntdll/unix/esync.c ────────────────────────────────────────────────

def patch_esync(c):
    if "do_msync()" in c:
        return None

    orig = c

    # Add the msync.h include
    if '#include "msync.h"' not in c:
        c_new = insert_after(c, '#include "esync.h"\n', '#include "msync.h"\n')
        if c_new:
            c = c_new

    # Modify do_esync() to return 0 if msync is active
    old = "do_esync_cached = getenv(\"WINEESYNC\") && atoi(getenv(\"WINEESYNC\"));"
    new = "do_esync_cached = getenv(\"WINEESYNC\") && atoi(getenv(\"WINEESYNC\")) && !do_msync();"
    result = replace_first(c, old, new)
    if result:
        c = result
    else:
        print("  WARN: could not patch do_esync() in esync.c")

    return c if c != orig else None

# ── dlls/ntdll/unix/sync.c ────────────────────────────────────────────────

APPLE_SYNC_WRAPPERS = r"""
#elif defined(__APPLE__)

static NTSTATUS linux_release_semaphore_obj( int obj, ULONG count, ULONG *prev_count )
{
    return msync_release_semaphore_obj( obj, count, prev_count );
}

static NTSTATUS linux_query_semaphore_obj( int obj, SEMAPHORE_BASIC_INFORMATION *info )
{
    return msync_query_semaphore_obj( obj, info );
}

static NTSTATUS linux_set_event_obj( int obj, LONG *prev_state )
{
    return msync_set_event_obj( obj, prev_state );
}

static NTSTATUS linux_reset_event_obj( int obj, LONG *prev_state )
{
    return msync_reset_event_obj( obj, prev_state );
}

static NTSTATUS linux_pulse_event_obj( int obj, LONG *prev_state )
{
    return msync_pulse_event_obj( obj, prev_state );
}

static NTSTATUS linux_query_event_obj( int obj, EVENT_BASIC_INFORMATION *info )
{
    return msync_query_event_obj( obj, info );
}

static NTSTATUS linux_release_mutex_obj( int obj, LONG *prev_count )
{
    return msync_release_mutex_obj( obj, prev_count );
}

static NTSTATUS linux_query_mutex_obj( int obj, MUTANT_BASIC_INFORMATION *info )
{
    return msync_query_mutex_obj( obj, info );
}

static NTSTATUS linux_wait_objs( int device, const DWORD count, const int *objs,
                                 BOOLEAN wait_any, int alert_fd, const LARGE_INTEGER *timeout )
{
    return msync_wait_objs( count, objs, wait_any, alert_fd, timeout );
}

"""

def patch_sync(c):
    # Insert Apple wrappers between Linux ntsync section and the #else stub
    if "msync_wait_objs" in c:
        return None  # already patched

    orig = c

    # Add msync.h include near the other sync includes
    if '#include "msync.h"' not in c:
        for anchor in ('#include "esync.h"\n', '#include "unix_private.h"\n'):
            result = insert_after(c, anchor, '#include "msync.h"\n')
            if result:
                c = result
                break
        else:
            print("  WARN: could not insert msync.h in sync.c")

    # The stub section starts with something like:
    # #else /* NTSYNC_IOC_EVENT_READ */
    for anchor in (
        "#else /* NTSYNC_IOC_EVENT_READ */\n",
        "#else\n\nstatic NTSTATUS linux_release_semaphore_obj",
        "\n#else\n\nstatic NTSTATUS linux_release_semaphore_obj",
    ):
        result = insert_before(c, anchor, APPLE_SYNC_WRAPPERS)
        if result:
            return result

    print("  WARN: could not find insertion point for Apple wrappers in sync.c")
    print("        Manually add the Apple linux_*_obj wrappers before the #else stub section.")
    return c if c != orig else None

# ── server/protocol.def ────────────────────────────────────────────────────

PROTOCOL_ADDITIONS = """
enum inproc_sync_type
{
    INPROC_SYNC_UNKNOWN   = 0,
    INPROC_SYNC_INTERNAL  = 1,
    INPROC_SYNC_EVENT     = 2,
    INPROC_SYNC_MUTEX     = 3,
    INPROC_SYNC_SEMAPHORE = 4,
};

/* Get the in-process synchronization fd associated with the waitable handle */
@REQ(get_inproc_sync_fd)
    obj_handle_t handle;        /* handle to the object */
@REPLY
    int           type;         /* inproc sync type */
    unsigned int access;        /* handle access rights */
    unsigned int shm_idx;       /* optional for index-based sync implementations */
@END


/* Get the in-process synchronization fd for the current thread user APC alerts */
@REQ(get_inproc_alert_fd)
@REPLY
    obj_handle_t handle;        /* alert fd is in flight with this handle */
@END

"""

def patch_protocol_def(c):
    if "get_inproc_sync_fd" in c:
        return None
    # Append before the last @END or at end
    # Find a good anchor — add just before the d3dkmt section or at the very end
    for anchor in ("/* Create a global d3dkmt", "/* End of requests */"):
        result = insert_before(c, anchor, PROTOCOL_ADDITIONS)
        if result:
            return result
    # Fallback: append
    return c + PROTOCOL_ADDITIONS

# ── server/object.h ────────────────────────────────────────────────────────

OBJECT_H_ADDITIONS = """
/* In-process synchronization (msync / ntsync) */
struct inproc_sync;
extern int get_inproc_device_fd(void);
extern int get_inproc_sync_fd( struct inproc_sync *sync );
extern struct inproc_sync *create_inproc_internal_sync( int manual, int signaled );
extern struct inproc_sync *create_inproc_event_sync( int manual, int signaled );
extern struct inproc_sync *create_inproc_semaphore_sync( unsigned int initial, unsigned int max );
extern struct inproc_sync *create_inproc_mutex_sync( thread_id_t owner, unsigned int count );
extern void abandon_inproc_mutexes( thread_id_t tid );
extern void signal_inproc_sync( struct inproc_sync *sync );
extern void reset_inproc_sync( struct inproc_sync *sync );
"""

def patch_object_h(c):
    if "get_inproc_device_fd" in c:
        return None
    # Add before the final #endif
    result = insert_before(c, "\n#endif /* __WINE_SERVER_OBJECT_H */", OBJECT_H_ADDITIONS)
    if result:
        return result
    result = insert_before(c, "#endif /* __WINE_SERVER_OBJECT_H */", OBJECT_H_ADDITIONS)
    if result:
        return result
    print("  WARN: could not patch server/object.h")
    return None

# ── server/thread.h ────────────────────────────────────────────────────────

def patch_thread_h(c):
    if "alert_sync" in c:
        return None
    # Add alert_sync field after the sync field in the thread struct
    result = replace_first(c,
        "    struct object         *sync;          /* sync object for server-side waits */\n",
        "    struct object         *sync;          /* sync object for server-side waits */\n"
        "    struct inproc_sync    *alert_sync;    /* inproc sync for user apc alerts */\n")
    if result:
        return result
    # Alternative field name patterns
    result = replace_first(c,
        "    struct object         *sync;\n",
        "    struct object         *sync;\n"
        "    struct inproc_sync    *alert_sync;    /* inproc sync for user apc alerts */\n")
    if result:
        return result
    print("  WARN: could not patch server/thread.h — add 'struct inproc_sync *alert_sync;' manually")
    return None

# ── server/thread.c ────────────────────────────────────────────────────────

def patch_thread_c(c):
    changed = False

    # 1. Add alert_sync creation in create_thread()
    if "create_inproc_internal_sync" not in c:
        old = "    if (!(thread->sync = create_internal_sync( 1, 0 ))) goto error;\n"
        new = ("    if (!(thread->sync = create_internal_sync( 1, 0 ))) goto error;\n"
               "    if (get_inproc_device_fd() >= 0 && !(thread->alert_sync = create_inproc_internal_sync( 1, 0 ))) goto error;\n")
        result = replace_first(c, old, new)
        if result:
            c = result
            changed = True
        else:
            print("  WARN: could not insert alert_sync creation in thread.c")

    # 2. signal_inproc_sync on APC queue (before wake_thread, inside the "first one" block)
    if "signal_inproc_sync" not in c:
        # Use the comment as anchor — unique in thread.c
        old = ("    if (!list_prev( queue, &apc->entry ))  /* first one */\n"
               "    {\n"
               "        wake_thread( thread );\n"
               "    }")
        new = ("    if (!list_prev( queue, &apc->entry ))  /* first one */\n"
               "    {\n"
               "        if (apc->call.type == APC_USER && thread->alert_sync)\n"
               "            signal_inproc_sync( thread->alert_sync );\n"
               "        wake_thread( thread );\n"
               "    }")
        result = replace_first(c, old, new)
        if result:
            c = result
            changed = True
        else:
            print("  WARN: could not insert signal_inproc_sync in thread.c")

    # 3. reset_inproc_sync in thread_cancel_apc and thread_dequeue_apc
    if "reset_inproc_sync" not in c:
        # thread_cancel_apc: insert before return inside the owner-match branch
        old = ("        signal_sync( apc->sync );\n"
               "        release_object( apc );\n"
               "        return;\n"
               "    }\n"
               "}\n"
               "\n"
               "/* remove the head apc")
        new = ("        signal_sync( apc->sync );\n"
               "        release_object( apc );\n"
               "        if (list_empty( &thread->user_apc ) && thread->alert_sync)\n"
               "            reset_inproc_sync( thread->alert_sync );\n"
               "        return;\n"
               "    }\n"
               "}\n"
               "\n"
               "/* remove the head apc")
        result = replace_first(c, old, new)
        if result:
            c = result
            changed = True
        else:
            print("  WARN: could not insert reset_inproc_sync in thread_cancel_apc")

    # 4. release alert_sync in destroy_thread
    if "thread->alert_sync" not in c:
        old = "    if (thread->sync) release_object( thread->sync );\n"
        new = ("    if (thread->alert_sync) release_object( thread->alert_sync );\n"
               "    if (thread->sync) release_object( thread->sync );\n")
        result = replace_first(c, old, new)
        if result:
            c = result
            changed = True
        else:
            print("  WARN: could not insert alert_sync release in destroy_thread")

    # 5. Send inproc device fd in init_first_thread reply
    if "inproc_device" not in c:
        # Find the reply->pid etc. block inside DECL_HANDLER(init_first_thread)
        old = ("    reply->pid          = get_process_id( process );\n"
               "    reply->tid          = get_thread_id( current );\n")
        new = ("    reply->pid          = get_process_id( process );\n"
               "    reply->tid          = get_thread_id( current );\n"
               "    if ((fd = get_inproc_device_fd()) >= 0)\n"
               "    {\n"
               "        reply->inproc_device = get_process_id( process ) | 1;\n"
               "        send_client_fd( process, fd, reply->inproc_device );\n"
               "    }\n")
        result = replace_first(c, old, new)
        if result:
            c = result
            changed = True
            # Also need 'int fd;' in the function
            old2 = "DECL_HANDLER(init_first_thread)\n{\n"
            new2 = "DECL_HANDLER(init_first_thread)\n{\n    int fd;\n"
            result2 = replace_first(c, old2, new2)
            if result2:
                c = result2
        else:
            print("  WARN: could not insert inproc_device sending in init_first_thread")

    # 6. Add get_inproc_alert_fd handler at end (before last newline or at end)
    if "get_inproc_alert_fd" not in c:
        handler = """

/* Get the in-process synchronization fd for the current thread user APC alerts */
DECL_HANDLER(get_inproc_alert_fd)
{
    int fd;

    if ((fd = get_inproc_sync_fd( current->alert_sync )) < 0) set_error( STATUS_INVALID_PARAMETER );
    else
    {
        if (do_msync())
        {
            reply->handle = (unsigned int)fd;
            return;
        }

        reply->handle = get_thread_id( current ) | 1; /* arbitrary token */
        send_client_fd( current->process, fd, reply->handle );
    }
}
"""
        c = c.rstrip() + "\n" + handler
        changed = True

    return c if changed else None

# ── server/event.c ─────────────────────────────────────────────────────────

def patch_event_c(c):
    if "create_inproc_event_sync" in c:
        return None

    # Add inproc check at top of create_event_sync function
    old = ("static struct object *create_event_sync( int manual, int signaled )\n"
           "{\n"
           "    struct event_sync *event;\n")
    new = ("static struct object *create_event_sync( int manual, int signaled )\n"
           "{\n"
           "    struct event_sync *event;\n"
           "\n"
           "    if (get_inproc_device_fd() >= 0) return (struct object *)create_inproc_event_sync( manual, signaled );\n")
    result = replace_first(c, old, new)
    if result:
        c = result

    # Also patch create_internal_sync if present
    old2 = ("struct object *create_internal_sync( int manual, int signaled )\n"
            "{\n"
            "    return (struct object *)create_server_internal_sync( manual, signaled );\n"
            "}")
    new2 = ("struct object *create_internal_sync( int manual, int signaled )\n"
            "{\n"
            "    if (get_inproc_device_fd() >= 0) return (struct object *)create_inproc_internal_sync( manual, signaled );\n"
            "    return (struct object *)create_server_internal_sync( manual, signaled );\n"
            "}")
    result2 = replace_first(c, old2, new2)
    if result2:
        c = result2

    return c

# ── server/mutex.c ─────────────────────────────────────────────────────────

def patch_mutex_c(c):
    if "create_inproc_mutex_sync" in c:
        return None
    old = ("static struct object *create_mutex_sync( int owned )\n"
           "{\n"
           "    struct mutex_sync *mutex;\n")
    new = ("static struct object *create_mutex_sync( int owned )\n"
           "{\n"
           "    struct mutex_sync *mutex;\n"
           "\n"
           "    if (get_inproc_device_fd() >= 0) return (struct object *)create_inproc_mutex_sync( owned ? current->id : 0, owned ? 1 : 0 );\n")
    result = replace_first(c, old, new)
    if result:
        return result
    print("  WARN: could not patch server/mutex.c")
    return None

# ── server/semaphore.c ─────────────────────────────────────────────────────

def patch_semaphore_c(c):
    if "create_inproc_semaphore_sync" in c:
        return None
    old = ("static struct object *create_semaphore_sync( unsigned int initial, unsigned int max )\n"
           "{\n"
           "    struct semaphore_sync *sem;\n")
    new = ("static struct object *create_semaphore_sync( unsigned int initial, unsigned int max )\n"
           "{\n"
           "    struct semaphore_sync *sem;\n"
           "\n"
           "    if (get_inproc_device_fd() >= 0) return (struct object *)create_inproc_semaphore_sync( initial, max );\n")
    result = replace_first(c, old, new)
    if result:
        return result
    print("  WARN: could not patch server/semaphore.c")
    return None

# ── main ───────────────────────────────────────────────────────────────────

def main():
    check_wine_root()
    print(f"\nApplying msync patch to Wine source in: {os.getcwd()}\n")

    print("1. Copying new source files...")
    copy_new_files()

    print("\n2. Patching existing files...")

    patches = [
        ("server/Makefile.in",              patch_server_makefile),
        ("server/main.c",                   patch_server_main),
        ("server/object.h",                 patch_object_h),
        ("server/thread.h",                 patch_thread_h),
        ("server/thread.c",                 patch_thread_c),
        ("server/event.c",                  patch_event_c),
        ("server/mutex.c",                  patch_mutex_c),
        ("server/semaphore.c",              patch_semaphore_c),
        ("server/protocol.def",             patch_protocol_def),
        ("dlls/ntdll/Makefile.in",          patch_ntdll_makefile),
        ("dlls/ntdll/unix/loader.c",        patch_loader),
        ("dlls/ntdll/unix/esync.c",         patch_esync),
        ("dlls/ntdll/unix/sync.c",          patch_sync),
    ]

    for path, fn in patches:
        if not os.path.exists(path):
            print(f"  SKIP  {path}  (not found — Wine version mismatch?)")
            continue
        patch_file(path, fn)

    print("\n3. Regenerating server_protocol.h from protocol.def...")
    if os.path.exists("tools/make_requests"):
        subprocess.run(["tools/make_requests"], check=False)
    else:
        print("  tools/make_requests not found — run './configure' first, then re-run this script.")
        print("  Or run: perl tools/make_requests (if perl is available)")

    print("\nDone! Now build Wine:")
    print("  ./configure --enable-archs=x86_64,i386 --without-x --without-opengl \\")
    print("    CFLAGS='-O2' && make -j$(sysctl -n hw.ncpu)")
    print("\nIf you see compilation errors, check the WARN messages above.")
    print("The msync patch is based on CrossOver's implementation (Wine 11.0).")
    print("Minor manual fixes may be needed for Wine 11.9 API changes.\n")

if __name__ == "__main__":
    main()
