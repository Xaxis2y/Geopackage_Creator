# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ISO 19115 / DGIWG Metadata Handler

Generates and manages ISO 19115-compliant metadata with DGIWG Defense Metadata
Framework (DMF) extensions.

This module creates:
- Package-level metadata (describes entire GeoPackage)
- Layer-level metadata (describes individual feature layers)
- Proper XML structure per ISO 19115 / DGIWG standards
- XSD Schema validation for DGIWG compliance
- Embedding in GeoPackage gpkg_metadata table

All metadata is embedded in the GeoPackage for portability and compliance.

Module version: v0.30.23


THREAD SAFETY (v0.30.10 - CRASH FIX)
------------------------------------
Everything in this module that touches lxml is serialized through one
process-wide re-entrant lock, `_LXML_LOCK`, and the compiled XSD is built
exactly once into a module-level singleton.

Why. The v0.30.9 test run died with a hard "Windows fatal exception: access
violation" inside `validate_schema()` at the `etree.fromstring()` call. The
faulting thread had already finished all of its GDAL work - the GeoPackage was
closed at converter.py:574 - and the other two worker threads were parked at
converter.py:109 waiting on the global conversion lock. GDAL serialization was
therefore working exactly as designed, and the crash was NOT a GDAL crash. It
was libxml2.

The hole was in this file. `MetadataHandler.__init__` called
`_load_iso19115_schema()`, which ran `etree.parse()` followed by
`etree.XMLSchema()` on every single instantiation. `GeoPackageConverter.__init__`
(converter.py:217) constructs a `MetadataHandler`, and the converter is
constructed INSIDE each worker thread - before `convert()` is called, so
outside the `_serialize_conversions` lock that protects everything else. Three
threads therefore compiled the XSD simultaneously.

Compiling an XML Schema is the single least thread-safe thing in libxml2.
`xmlSchemaParse()` populates and interns into shared string dictionaries, wires
up the global structured-error handler and resolves imports/includes through
shared caches. Two of those running at once corrupts the heap. Heap corruption
does not fault where it happens - it faults at the next allocation from the
same arena, which here was the `etree.fromstring()` a few hundred microseconds
later, in whichever thread got there first. That is precisely the shape of the
reported traceback.

The fix has three parts:

1. `_get_shared_schema()` compiles the XSD once, under `_LXML_LOCK`, and every
   `MetadataHandler` reuses that one object. The race window is closed rather
   than narrowed, because the second and third callers never enter
   `etree.XMLSchema()` at all. It is also a straight performance win: the XSD
   was previously re-parsed for every converter ever built.
   [v0.30.23: this specific mechanism - a compiled schema reused across
   MetadataHandler instances - was later found to crash for an unrelated
   reason (a compiled schema surviving a GDAL write) and was removed; see
   "SCHEMA LIFETIME VS GDAL WRITES" below. The thread-safety problem THIS
   section fixed - two threads inside `etree.XMLSchema()` at once - remains
   correctly fixed by serializing on `_LXML_LOCK`, which `_compile_schema_
   fresh()` (the current replacement for `_get_shared_schema()`) still does.]

2. `validate_schema()` holds `_LXML_LOCK` across the whole parse-validate-read
   -error_log sequence. An `lxml` `XMLSchema` object is explicitly documented as
   NOT safe for concurrent `.validate()` calls, and `schema.error_log` is
   mutable state living ON that shared object - two threads validating at once
   would interleave their error lists even if libxml2 did not fault. Holding
   the lock across all three steps makes the reported errors belong to the
   document that was just validated.

3. Parsing is done with an explicit, hardened parser (`no_network=True`,
   `resolve_entities=False`) rather than lxml's implicit default parser. This
   removes one more piece of shared mutable state from the picture and, for a
   tool that validates metadata for defense customers, closes XXE and
   billion-laughs as a side effect.

The stdlib `xml.etree.ElementTree.fromstring()` well-formedness checks are left
unlocked on purpose. Those run on expat, each call builds its own independent
parser, and they share nothing with libxml2.

Cost of serializing. Schema validation of a ~4 KB metadata document is on the
order of a millisecond; a conversion is seconds to minutes. The lock is
uncontended in the shipped GUI and CLI, which never run two conversions at
once, and is noise even in the 3-thread test.


LIBXML2 ABI FAIL-FAST GUARD (v0.30.13 - ROOT CAUSE CONFIRMED)
--------------------------------------------------------------
v0.30.10 fixed a real thread-safety hole, but the 2026-08-04 access violation
kept reproducing afterward - including single-threaded, with no race
involved. `diagnose_crash_v0.30.11.py` and `diagnose_crash_v0.30.12.py`
bisected the actual cause with two subprocess-isolated experiments:

    heavy_no_lxml     the full GDALHandler + sqlite3-embedding + DGIWG
                      finalization pipeline, with lxml touched ZERO times
                      anywhere in the process              -> clean 5/5

    gdal_then_schema  ~20 lines, no project code: compile the bundled XSD via
                      `etree.XMLSchema()`, perform ONE GDAL vector write via
                      plain osgeo calls, then make any further lxml call
                                                              -> CRASHED 5/5,
                      identical Windows access violation every time, at the
                      first lxml call after the write

Same machine, same GDAL build, only variable was whether lxml compiled a
schema before a GDAL write happened in the same process. That is dispositive:
the fault requires lxml, and does not require anything specific to this
project's conversion pipeline beyond "a GDAL write happened."

The environment's `dll_map` fingerprint explains why:

    LIBXML_COMPILED_VERSION : (2, 14, 6)   <- what this lxml build expects
    LIBXML_VERSION (runtime): (2, 15, 3)   <- the libxml2.dll actually loaded

Exactly one libxml2 image is mapped into the process - GDAL and lxml share
it, they are not fighting over two separate copies. But lxml's compiled
extension was built against 2.14.6's internal structure layouts, and the DLL
resolved at runtime is 2.15.3. Windows does not enforce ABI compatibility at
load time the way a strict soname check would; the mismatched DLL loads and
runs right up until something dereferences a structure whose layout changed,
which is what a GDAL write reliably provokes.

GDAL's own version was independently ruled out as the variable - this
reproduced under GDAL 3.13.1, and the project has since moved its tested pin
to 3.13.2 (see core/config.py GDAL_TESTED_VERSION) purely as a support
decision. It is NOT a fix for this crash; the libxml2 ABI mismatch is
orthogonal to which GDAL patch version is installed, and would reproduce
under either.

Because this is an environment defect the code cannot repair, the correct
in-process behaviour is to refuse the dangerous operation loudly rather than
let it corrupt memory silently. `_verify_libxml2_abi()` runs immediately
before the ONE operation proven to set up the fault - compiling the XSD - and
raises `RuntimeError` with the exact remediation steps unless
`config.ALLOW_LIBXML_ABI_MISMATCH` has been explicitly set `True` by someone
who has verified their specific combination is safe. A clear exception before
any conversion starts is a strictly better failure mode than an opaque native
crash minutes in, or during interpreter shutdown with no Python traceback at
all - which is what every user of this tool got until this version.

Note: this guard's own diagnosis (a libxml2 VERSION mismatch) turned out to
be necessary but not sufficient - see the next section. It is retained
unchanged because a version mismatch is a real, independent defect that must
still be caught, even though fixing it alone does not fix the crash.


SCHEMA LIFETIME VS GDAL WRITES (v0.30.20-23 - THE ACTUAL ROOT CAUSE)
---------------------------------------------------------------------
v0.30.20 pinned `libxml2=2.14` in `environment.yml` on the theory that the
ABI guard's version mismatch WAS the crash. That pin was deployed and tested
on the real Windows/Anaconda machine on 2026-08-14: `LIBXML_COMPILED_VERSION`
and `LIBXML_VERSION` now BOTH read `(2, 14, 6)` - a perfect match - and the
identical Windows access violation still occurred, at this file's own
`validate_schema()`, during ordinary test runs. Version agreement was
necessary but not sufficient. That release's "root cause found" claim was
wrong and was corrected in `CHANGELOG_v0.30.20.md`.

Two follow-up diagnostics (`dev_tools/diagnose_crash_v0.30.21.py`, `_v0.30.22.py`,
both run on the real target machine, GDAL 3.13.2 + lxml 6.1.1, matched
libxml2 2.14.6 both sides) isolated the real mechanism by subprocess-probing
every combination of "compile a schema" / "GDAL vector write" / "use or free
the schema" in different orders:

    compiled BEFORE a write, used/freed AFTER it      -> CRASHES, always
    compiled AFTER a write, used immediately            -> fine
    compiled AFTER a write, reused across a 2nd write   -> CRASHES too (!)
    compiled fresh immediately before EVERY use,
      discarded immediately after, repeated 4x          -> fine, every time

The decisive result is the third line. It rules out the "GDAL disturbs
libxml2's global state exactly once, lazily, on first use" theory - a schema
safely compiled after one write still does not survive a SECOND write. GDAL's
GeoPackage write path disturbs live libxml2 objects on every single write,
not once. Consequently NO compiled `etree.XMLSchema` can ever be reused
across more than the one write immediately preceding its own compilation -
caching one for the life of the process, which is exactly what `_SHARED_SCHEMA`
did from v0.30.10 through v0.30.22, is unsafe by construction, independent of
thread-safety and independent of the libxml2 version pin.

v0.30.23 removes the compiled-schema cache entirely. `_compile_schema_fresh()`
parses and compiles a brand-new `XMLSchema` on every single call; nothing
above it - not `MetadataHandler.__init__`, not the `schema` property, not
`validate_schema()` - stores the result anywhere that could outlive the one
call using it. Only the schema FILE's filesystem location is still cached
(`_locate_schema_file()` touches no libxml2 state at all, independently
confirmed safe by `diagnose_crash_v0.30.21.py` probes P1-P3). This trades away
the performance win `_SHARED_SCHEMA` existed for - every `validate_schema()`
call now re-parses and re-compiles the XSD - in exchange for actually not
crashing, which no amount of thread-safety or version-pinning achieved.


PERSISTENT LXML WORKER THREAD (v0.30.24 - A FOURTH, DISTINCT ROOT CAUSE)
--------------------------------------------------------------------------
v0.30.23 fixed schema-lifetime-vs-GDAL-writes and was believed, at the time,
to be the last of the access-violation crashes in this module. It was not.
A separate crash kept reproducing afterward, with all three of the fixes
above intact and unmodified: run one conversion to completion on one thread,
`join()` it, then start a second, brand-new thread and convert a second
file. `dev_tools/diagnose_crash_v0.30.17.py` through `_v0.30.37.py` bisected
it on the real target machine using the real, unmodified pipeline (never a
hand-rolled approximation) and pinned the necessary condition down precisely
by probes P51/P52/P53 (`diagnose_crash_v0.30.34.py`): ONE thread must
perform a real GDAL write and a real lxml schema-file touch itself, in that
order, within that same thread. Only then does a later, different,
freshly-created thread's first lxml touch crash. Split GDAL-only and
lxml-only activity across two threads that each do only one - in either
order - and it does not crash, in any run so far.

This is a fourth, distinct mechanism from the three sections above. There is
no concurrent compilation (thread A has fully finished and been joined
before thread B is even created, so the v0.30.10 race this file already
serializes against does not apply). There is no ABI mismatch on the machine
every one of these probes ran on. And there is no compiled schema surviving
a GDAL write (`_compile_schema_fresh()` still recompiles from scratch on
every call, exactly as v0.30.23 designed it to - the crash reproduces with
that fix fully intact). What matters here is something scoped to the OS
thread itself - which specific thread touches lxml, and whether a DIFFERENT
thread touched GDAL immediately before it - not any shared, process-wide
libxml2 state that the first three fixes already serialize or refresh
correctly.

The fix: no thread is allowed to perform both a GDAL write and an lxml touch
itself, ever. GDAL work stays exactly where it already is, on whichever
worker thread a conversion runs on. Every lxml touch - which in this module
means every real call into `_compile_schema_fresh()` and `etree.fromstring()`
/`schema.validate()` made by `validate_schema()` - is instead handed off to
ONE persistent worker thread (`_ensure_lxml_worker_started()` /
`_lxml_worker_loop()` below), created once on first use and reused for the
rest of the process's life, never recreated. Since no thread ever does "GDAL
then lxml itself" anymore, the confirmed necessary condition can never
arise. `validate_schema()`'s public contract - return `True`, or raise the
same `ValueError` with the same message, from the CALLING thread - is
unchanged; only where the actual libxml2 work executes has moved. The
`schema` property and `_load_iso19115_schema()` are left exactly as they
were, still synchronous, still running on whichever thread calls them:
neither is reachable from `GeoPackageConverter.convert()` except THROUGH
`validate_schema()`, and both are used directly, from a single thread, with
no preceding GDAL write on that same thread, by this project's own test
suite - there is no observed or plausible path through which either one
participates in the crash.

Validated, before this was written, in an isolated diagnostic harness that
monkey-patches this real module rather than approximating it: safe for one
round (`diagnose_crash_v0.30.34.py` P52), safe across 5 repeated sequential
rounds (`_v0.30.35.py` P55), safe under one batch of 4 threads attempting to
run concurrently (`_v0.30.36.py` P57), and safe across 3 repeated batches of
4 (`_v0.30.37.py` P59 - 12 total conversions, one confirmed worker-thread
identity throughout). Reading `geopackage_creator_gui.py` and
`core/gdal_handler.py` afterward confirmed the shipped GUI and CLI can only
ever produce the strictly-sequential pattern in production - `start_
conversion()` refuses a second conversion thread while one is in flight, and
`converter._serialize_conversions` already holds a process-wide lock (added
in v0.30.7, for the unrelated handle-lifetime crash that section fixed)
around the whole of `convert()` regardless - so P52/P55 are the
directly-applicable evidence; P57/P59 add confidence for any future,
currently-nonexistent code path that runs conversions concurrently.

That dev_tools harness testing is not, by itself, the same claim as "this
patch is correct in the shipped product." `dev_tools/validate_patch_
v0.30.38.py` runs the same kind of check against this actual file, in place,
through the real `GeoPackageConverter.convert()` end to end with nothing
monkey-patched - see that script for the current result. As with every fix
in this module's history, treat this as proven on the target machine, not
proven by inspection.
"""

import uuid
import logging
import queue
import threading
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
import xml.sax.saxutils as saxutils
import xml.etree.ElementTree as ET

from lxml import etree

from .config import (
    DMF_STANDARD_URI,
    METADATA_MIME_TYPE,
    SECURITY_CODE_MAP,
)


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


__version__ = "0.30.24"


# ---------------------------------------------------------------------------
# Process-wide lxml serialization (v0.30.10 - see module docstring)
# ---------------------------------------------------------------------------
#
# Re-entrant, because `generate_package_metadata()` calls `validate_schema()`
# and a future caller may reasonably want to hold the lock across several
# validations without deadlocking itself.
_LXML_LOCK = threading.RLock()

# v0.30.23: ONLY the schema file's resolved location is cached now - never a
# compiled XMLSchema object. See the module docstring's "SCHEMA LIFETIME VS
# GDAL WRITES" section: a compiled schema that survives even one GDAL write
# past its own creation crashes, so no compiled schema may ever be process-
# wide state. `_SCHEMA_KNOWN_BROKEN` avoids retrying a doomed parse of a
# malformed XSD on every single call; it caches a FAILURE outcome only,
# never a live object, so it carries none of the risk the old
# `_SHARED_SCHEMA` did.
_SCHEMA_PATH_RESOLVED: bool = False
_SCHEMA_SOURCE_PATH: Optional[Path] = None
_SCHEMA_KNOWN_BROKEN: bool = False


def lxml_lock() -> threading.RLock:
    """Return the process-wide lxml lock.

    Exposed so that callers who reach into lxml directly - a custom validator,
    a report generator that pretty-prints an XML tree - can serialize against
    this module rather than racing it. Anything in this process that calls into
    libxml2 from more than one thread should hold this.

    Returns:
        The module-level `threading.RLock` guarding all libxml2 access.
    """
    return _LXML_LOCK


# ---------------------------------------------------------------------------
# Persistent lxml worker thread (v0.30.24 - see module docstring's
# "PERSISTENT LXML WORKER THREAD" section for the full evidence trail).
#
# `validate_schema()` no longer touches lxml on the calling thread at all.
# It hands the work to this ONE worker thread instead - created lazily on
# first use and never recreated - so no thread in this process can ever
# perform a GDAL write and an lxml touch itself, which
# `dev_tools/diagnose_crash_v0.30.34.py` probes P51/P52/P53 pinned down as
# the exact, necessary precondition for the access violation this fixes.
# ---------------------------------------------------------------------------

# How long `validate_schema()` waits for the worker to respond before giving
# up and raising, rather than hanging the calling thread (and, in the
# shipped GUI, the whole application) forever. The module docstring notes
# schema validation of a ~4 KB document is normally on the order of a
# millisecond, so this is a generous ceiling for a genuine hang, not a
# realistic expected wait.
_LXML_WORKER_RESPONSE_TIMEOUT = 30

# The job queue the worker thread consumes. Each job is a
# (handler, xml_bytes, response_queue) tuple; only `validate_schema()` below
# ever puts onto this queue.
_LXML_JOBS: "queue.Queue" = queue.Queue()

# The worker thread itself, and the lock guarding its lazy, one-time start.
# Double-checked locking: the fast path (worker already running, the normal
# case for every call after the first) never touches the lock at all.
_LXML_WORKER_THREAD: Optional[threading.Thread] = None
_LXML_WORKER_STARTUP_LOCK = threading.Lock()


def _ensure_lxml_worker_started() -> None:
    """Start the persistent lxml worker thread if it is not already running.

    Safe to call from any thread, any number of times - only the first
    caller (of however many threads race here, e.g. several converter
    threads each calling `validate_schema()` for the first time at nearly
    the same moment) actually creates the thread; everyone else sees
    `_LXML_WORKER_THREAD is not None` and returns immediately, either on the
    lock-free fast path or after briefly waiting for the lock.
    """
    global _LXML_WORKER_THREAD

    if _LXML_WORKER_THREAD is not None:
        return

    with _LXML_WORKER_STARTUP_LOCK:
        if _LXML_WORKER_THREAD is not None:
            return
        t = threading.Thread(
            target=_lxml_worker_loop,
            name="MetadataHandler-lxml-worker",
            daemon=True,
        )
        t.start()
        _LXML_WORKER_THREAD = t
        logger.debug("Started persistent lxml worker thread (v0.30.24)")


def _validate_schema_impl(handler: "MetadataHandler", xml_bytes: bytes) -> bool:
    """The real validation logic. Runs ONLY on the persistent lxml worker
    thread, via `_lxml_worker_loop()` - never call this directly. This is
    the v0.30.23 body of `MetadataHandler.validate_schema()`, moved here
    unchanged except for `self` becoming an explicit `handler` parameter, so
    that it is textually obvious this function's caller determines which
    thread it runs on, and that caller is now always the same one thread.

    Args:
        handler: the `MetadataHandler` instance `validate_schema()` was
            called on. Reading `handler.schema` here (not on the calling
            thread) is exactly the point of this refactor.
        xml_bytes: the metadata XML, already UTF-8 encoded by the calling
            thread - pure Python string work, not moved here because it
            touches no libxml2 state and gains nothing from running on the
            worker.

    Returns:
        True if valid.

    Raises:
        ValueError: if XML fails schema validation, is not well-formed, or
            any other validation error occurs - identical to the exceptions
            `validate_schema()` raised before v0.30.24.
    """
    with _LXML_LOCK:
        # v0.30.23: compiled fresh, INSIDE the lock, immediately before use -
        # see the module docstring's "SCHEMA LIFETIME VS GDAL WRITES"
        # section. `_LXML_LOCK` is an RLock, so `handler.schema`'s own
        # internal lock acquisition inside `_compile_schema_fresh()` nests
        # safely here. v0.30.24: this lock is no longer load-bearing for
        # thread-safety - only the one worker thread ever reaches this
        # function - but it costs nothing uncontended and is kept as
        # defense-in-depth against some future second caller.
        schema = handler.schema
        if not schema:
            logger.warning("No XSD schema available for validation")
            return True  # Skip validation if schema not loaded

        try:
            # Parse XML string with a hardened, per-call parser
            doc = etree.fromstring(xml_bytes, _build_hardened_parser())

            # Validate against schema
            if not schema.validate(doc):
                errors = schema.error_log
                error_details = "\n".join(
                    f"  Line {e.line}: {e.message}" for e in errors
                )
                raise ValueError(
                    f"ISO 19115 schema validation failed:\n{error_details}"
                )

            logger.info("ISO 19115 schema validation passed")
            return True

        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML syntax: {e}")
        except ValueError:
            # Already the message we want - do not double-wrap it as
            # "Schema validation error: ISO 19115 schema validation
            # failed: ..." the way the pre-v0.30.10 ordering did.
            raise
        except Exception as e:
            raise ValueError(f"Schema validation error: {e}")


def _lxml_worker_loop() -> None:
    """Body of the persistent lxml worker thread. Never returns.

    Pulls one (handler, xml_bytes, response_queue) job at a time from
    `_LXML_JOBS` and runs it through `_validate_schema_impl()`. This is the
    ONLY place in the process, after v0.30.24, that ever calls
    `_validate_schema_impl()` - which is exactly what makes it the only
    thread that ever touches lxml through `validate_schema()`.

    `except Exception` (not a narrower type) is deliberate defense-in-depth:
    `_validate_schema_impl()` already converts everything it expects into
    `ValueError`, so in practice only `ValueError` should ever be caught
    here, but if some future edit ever lets a different exception type
    escape, catching it broadly here means one bad document fails that one
    call - via the normal `(False, exc)` error path below - rather than
    killing this thread and silently hanging every `validate_schema()` call
    for the rest of the process's life waiting on a worker that no longer
    exists.
    """
    while True:
        handler, xml_bytes, response_q = _LXML_JOBS.get()
        try:
            result = _validate_schema_impl(handler, xml_bytes)
            response_q.put((True, result))
        except Exception as e:
            response_q.put((False, e))


def _build_hardened_parser() -> etree.XMLParser:
    """Return a fresh, hardened lxml parser.

    Built per call rather than cached: an `XMLParser` carries mutable state
    (its own error log, and the tree it is currently building), so a shared one
    is another thread-safety hazard of exactly the kind this release removes.
    Construction is cheap relative to the parse that follows.

    Hardening:
        no_network=True        - never fetch a DTD or schema over the wire
        resolve_entities=False - no entity expansion, which closes both XXE
                                 (file:// disclosure) and the billion-laughs
                                 expansion DoS
        huge_tree=False        - keep libxml2's depth/size guards armed

    Returns:
        A new `etree.XMLParser` instance.
    """
    return etree.XMLParser(
        no_network=True,
        resolve_entities=False,
        huge_tree=False,
    )


def _verify_libxml2_abi() -> None:
    """Raise if lxml was compiled against a different libxml2 than it loaded.

    v0.30.13. Confirmed root cause of the 2026-08-04/05 access violations -
    see the module docstring's "LIBXML2 ABI FAIL-FAST GUARD" section for the
    full evidence trail (dev_tools/diagnose_crash_v0.30.11.py / _v0.30.12.py,
    changelogs/CHANGELOG_v0.30.13.md). In summary: `heavy_no_lxml` (full conversion
    pipeline, lxml touched zero times) ran clean 5/5; `gdal_then_schema`
    (~20 lines, no project code: compile an XSD via lxml, do one GDAL vector
    write, touch lxml again) crashed 5/5 with an identical access violation.
    Same machine, same GDAL build - only variable was lxml involvement.

    Deliberately not cached at all. A tuple comparison costs nothing, and
    caching a "checked" flag would let a caller who retries after catching
    the `RuntimeError` slip through on the second attempt - defeating the
    guard on exactly the retry path most likely to happen in practice. (Prior
    to v0.30.23 this docstring contrasted this with "the compiled schema,
    which IS cached" - as of v0.30.23 nothing here is cached anymore; see the
    module docstring's "SCHEMA LIFETIME VS GDAL WRITES" section. This
    function's own behaviour - re-check every call, cache nothing - was
    always correct and is unchanged.)

    Raises:
        RuntimeError: if the compiled and runtime libxml2 versions differ and
            `config.ALLOW_LIBXML_ABI_MISMATCH` is not `True`.
    """
    try:
        compiled = etree.LIBXML_COMPILED_VERSION
        runtime = etree.LIBXML_VERSION
    except AttributeError:
        # Old lxml build without these attributes - nothing to compare, and
        # no evidence that build carries this defect. Let it proceed.
        return

    if compiled == runtime:
        return

    message = (
        "lxml/libxml2 ABI mismatch: lxml was compiled against libxml2 "
        f"{compiled} but the libxml2 loaded at runtime is {runtime}. This "
        "exact combination is a confirmed cause of a Windows access "
        "violation in this tool (see dev_tools/diagnose_crash_v0.30.12.log "
        "and changelogs/CHANGELOG_v0.30.13.md): compiling this XSD via lxml followed by a "
        "GDAL vector write and any further lxml call crashed 5/5 times in "
        "testing, with no project code involved. Every GeoPackage conversion "
        "this tool performs follows exactly that sequence.\n"
        "\n"
        "Fix the environment (recommended - lets conda's solver pick a "
        "mutually consistent set, rather than layering another install on "
        "top of a drifted one):\n"
        "  conda deactivate\n"
        "  conda env remove -n geopackage\n"
        "  conda env create -f environment.yml\n"
        "  conda activate geopackage\n"
        "\n"
        "Then confirm the two versions agree:\n"
        "  python -c \"from lxml import etree; "
        "print(etree.LIBXML_COMPILED_VERSION, etree.LIBXML_VERSION)\"\n"
        "\n"
        "If you have independently verified this specific combination is "
        "safe on your build, set core.config.ALLOW_LIBXML_ABI_MISMATCH = "
        "True to downgrade this to a logged warning."
    )

    # Imported locally (not at module load) so the module read through it
    # every call, matching converter._serialize_conversions's own reasoning:
    # the flag can be flipped at runtime rather than only before first import.
    from . import config as _config

    if getattr(_config, "ALLOW_LIBXML_ABI_MISMATCH", False):
        logger.warning(
            "%s Continuing because config.ALLOW_LIBXML_ABI_MISMATCH is True.",
            message,
        )
        return

    raise RuntimeError(message)


def _locate_schema_file() -> Optional[Path]:
    """Return the path of the bundled ISO 19139 XSD, or None if absent.

    v0.27.0 housekeeping: the bundled schema validates the ISO 19139 (2005
    'gmd') ENCODING of ISO 19115 metadata, so it is named iso19139-gmd.xsd.
    The legacy filename is still accepted as a fallback.

    Returns:
        Path to the schema file, or None when neither name exists.
    """
    schema_dir = Path(__file__).parent.parent / "schemas"

    schema_path = schema_dir / "iso19139-gmd.xsd"
    if schema_path.exists():
        return schema_path

    legacy_path = schema_dir / "iso19115-1.xsd"
    if legacy_path.exists():
        return legacy_path

    return None


def _compile_schema_fresh() -> Optional[etree.XMLSchema]:
    """Compile a brand-new ISO 19115/19139 `XMLSchema`, on every single call.

    v0.30.23: replaces the old process-wide cache (`_get_shared_schema()` /
    module-level `_SHARED_SCHEMA`, v0.30.10-v0.30.22). See the module
    docstring's "SCHEMA LIFETIME VS GDAL WRITES" section: `diagnose_crash_
    v0.30.22.py`, run on the real target machine, proved that a compiled
    schema reused across a GDAL write crashes even when the schema was itself
    compiled after an EARLIER write (probe P9) - only recompiling fresh
    immediately before each use, and discarding it immediately after,
    survived repeated write/validate cycles (probe P10). This is not a
    thread-safety property, it is a lifetime property: the caller MUST use
    the returned object immediately and let its reference drop before any
    further GDAL write happens, in this thread or any other.

    Only the schema FILE's filesystem location is cached across calls -
    `_locate_schema_file()` is pure `Path.exists()` work with no libxml2
    involvement whatsoever, independently confirmed safe
    (`diagnose_crash_v0.30.21.py` probes P1-P3). A schema file that fails to
    parse/compile is also remembered as broken, so a permanently malformed
    XSD does not re-attempt (and re-log) a doomed parse on every call - that
    caches a FAILURE, never a live object, so it carries none of the risk
    `_SHARED_SCHEMA` did.

    Returns:
        A freshly compiled `etree.XMLSchema`, or None if no usable schema
        file exists, or the file fails to compile.
    """
    global _SCHEMA_PATH_RESOLVED, _SCHEMA_SOURCE_PATH, _SCHEMA_KNOWN_BROKEN

    with _LXML_LOCK:
        if not _SCHEMA_PATH_RESOLVED:
            _SCHEMA_SOURCE_PATH = _locate_schema_file()
            _SCHEMA_PATH_RESOLVED = True
            if _SCHEMA_SOURCE_PATH is None:
                logger.warning(
                    "ISO 19115 schema not found in "
                    f"{Path(__file__).parent.parent / 'schemas'} - "
                    "XSD validation will be skipped"
                )

        if _SCHEMA_SOURCE_PATH is None or _SCHEMA_KNOWN_BROKEN:
            return None

        # v0.30.13: still gate every single compile, not just the first, as
        # before. `_verify_libxml2_abi()` is a cheap tuple comparison (see its
        # own docstring for why it is deliberately not cached), and this
        # function now runs far more often than the old cached path did -
        # which is correct, since v0.30.20 proved ABI-matched libxml2 alone
        # does not make compiling here safe either; this guard remains cheap
        # insurance against a version regression stacked on top of the
        # structural fix this function IS.
        _verify_libxml2_abi()

        try:
            # Parse schema document with the hardened parser, then compile.
            # Both steps stay inside the lock: xmlSchemaParse() is the unsafe
            # one, and the document it consumes is interned into shared
            # dictionaries, so neither may overlap with another thread.
            schema_doc = etree.parse(
                str(_SCHEMA_SOURCE_PATH), _build_hardened_parser()
            )
            schema = etree.XMLSchema(schema_doc)
            logger.debug(f"Compiled ISO 19115 schema from {_SCHEMA_SOURCE_PATH}")
            return schema

        except Exception as e:
            logger.warning(f"Error loading ISO 19115 schema: {e}")
            _SCHEMA_KNOWN_BROKEN = True
            return None


def reset_schema_cache() -> None:
    """Drop the cached schema FILE LOCATION so the next call re-resolves it.

    v0.30.23: there is no compiled schema object to drop anymore - every call
    to `_compile_schema_fresh()` already compiles fresh. This now resets only
    the resolved path and the "known broken" flag, so a test can swap the
    file in schemas/ and have it be re-located (and, if previously marked
    broken, re-attempted) on the next call.

    Not safe to call while another thread is inside `validate_schema()`; call
    it from single-threaded test setup or teardown only.
    """
    global _SCHEMA_PATH_RESOLVED, _SCHEMA_SOURCE_PATH, _SCHEMA_KNOWN_BROKEN

    with _LXML_LOCK:
        _SCHEMA_PATH_RESOLVED = False
        _SCHEMA_SOURCE_PATH = None
        _SCHEMA_KNOWN_BROKEN = False
        logger.debug("ISO 19115 schema location cache reset")


def get_schema_source_path() -> Optional[Path]:
    """Return the resolved path the schema is compiled from on each call.

    v0.30.23: this is the schema FILE's location, cached because locating it
    is pure filesystem I/O. It is no longer tied to a single compiled
    schema instance - every `_compile_schema_fresh()` call recompiles fresh
    from this same path.

    Returns:
        The `Path` of the schema file, or None if none was found (or none has
        been resolved yet - call `_compile_schema_fresh()` or construct a
        `MetadataHandler` first).
    """
    return _SCHEMA_SOURCE_PATH


class MetadataHandler:
    """
    Generates ISO 19115 / DGIWG-compliant metadata with XSD validation.

    Handles creation of metadata XML documents for embedding in
    GeoPackage files. Ensures compliance with both OGC standards
    and DGIWG defense requirements through XSD schema validation.

    v0.30.10-v0.30.22: instances were cheap because the compiled XSD was a
    process-wide singleton, so construction never parsed a schema. v0.30.23
    REMOVES that singleton - see the module docstring's "SCHEMA LIFETIME VS
    GDAL WRITES" section for why a schema compiled once and reused across
    GDAL writes crashes on the real target machine, version-matched libxml2
    or not. Construction is still cheap (it does no lxml work at all now),
    but `schema` is a property that compiles fresh on every access, so
    reading it repeatedly is no longer free the way it used to be. Instances
    remain safe to create and use from multiple threads - all libxml2 work is
    still serialized on the module lock.

    Attributes:
        schema: PROPERTY (v0.30.23), not a stored value - compiles a brand
            new ISO 19115 XSD `etree.XMLSchema` on every access, or None when
            no schema is bundled or it fails to compile. Do not hold a
            reference to it across any GDAL operation; use it immediately and
            let it go out of scope. See `_compile_schema_fresh()`.
        namespace_map: XML namespace mappings
    """

    def __init__(self):
        """Initialize metadata handler.

        v0.30.23: no longer compiles or binds a schema here - `schema` is a
        property now (see the class docstring), computed fresh on each
        access rather than once at construction. `_verify_libxml2_abi()` is
        still called here, on its own, purely so a version mismatch is still
        reported at the earliest possible point (construction) rather than
        silently deferred to first use - it no longer gates a compile
        happening in this method, because no compile happens in this method
        at all anymore.

        Raises:
            RuntimeError: if this is the first MetadataHandler built in the
                process and lxml's compiled libxml2 ABI does not match the
                libxml2 loaded at runtime. See `_verify_libxml2_abi()`.
        """
        self.namespace_map = {
            "gmd": "http://www.isotc211.org/2005/gmd",
            "gco": "http://www.isotc211.org/2005/gco",
            "gml": "http://www.opengis.net/gml/3.2",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }
        _verify_libxml2_abi()

    @property
    def schema(self) -> Optional[etree.XMLSchema]:
        """Freshly compiled ISO 19115 XSD schema, or None if unavailable.

        v0.30.23: a PROPERTY, not a stored attribute - every single access
        parses and compiles a brand-new `etree.XMLSchema`. Never store the
        result of reading this on `self`, in a module global, or anywhere
        else that could outlive the statement using it - see the module
        docstring's "SCHEMA LIFETIME VS GDAL WRITES" section for the evidence
        that doing so crashes on the real target machine.

        Returns:
            A freshly compiled schema, or None if no usable schema file
            exists or it fails to compile.
        """
        return _compile_schema_fresh()

    def _load_iso19115_schema(self) -> Optional[etree.XMLSchema]:
        """
        Load ISO 19115 XSD schema for metadata validation.

        Retained for backward compatibility. v0.30.23: delegates to the same
        fresh-compile-every-call path the `schema` property uses - callers of
        this method must follow the same rule, use the result immediately and
        do not store it.

        Returns:
            A freshly compiled lxml XMLSchema object, or None if the schema
            file is not found or fails to compile.
        """
        return _compile_schema_fresh()

    def validate_schema(self, metadata_xml_string: str) -> bool:
        """
        Validate metadata XML against ISO 19115 XSD schema.

        Performs full XSD schema validation to ensure DGIWG compliance.
        Checks required fields, element types, and structure.

        v0.30.24: this method no longer touches lxml on the calling thread
        AT ALL. See the module docstring's "PERSISTENT LXML WORKER THREAD"
        section: the actual work - compile the schema fresh, parse the
        document, validate, read error_log - now runs on one persistent
        worker thread (`_validate_schema_impl()`, via `_lxml_worker_loop()`),
        because `dev_tools/diagnose_crash_v0.30.34.py` probes P51/P52/P53
        proved that the same thread doing a real GDAL write and a real lxml
        touch itself - which every conversion, including this call site
        through `GeoPackageConverter.convert()`, previously did - is what a
        later, different thread's first lxml touch needs in order to crash.
        This method's own contract is unchanged: it still returns `True` or
        raises `ValueError` with the same messages, on the calling thread,
        as it always has. Only where the libxml2 work actually executes has
        moved.

        Args:
            metadata_xml_string: XML string to validate

        Returns:
            True if valid

        Raises:
            ValueError: If XML fails schema validation
            RuntimeError: If the persistent lxml worker thread does not
                respond within `_LXML_WORKER_RESPONSE_TIMEOUT` seconds -
                should never happen in normal operation; see
                `_lxml_worker_loop()`.

        Examples:
            >>> handler = MetadataHandler()
            >>> xml = handler.generate_package_metadata(...)
            >>> handler.validate_schema(xml)  # Raises if invalid
            True
        """
        # Encode on the CALLING thread - pure Python string work, no
        # libxml2, so there is no reason to burden the persistent worker
        # with it, and a bad input type fails immediately rather than
        # round-tripping through the queue first.
        try:
            xml_bytes = metadata_xml_string.encode("utf-8")
        except (AttributeError, UnicodeEncodeError) as e:
            raise ValueError(f"Invalid XML input: {e}")

        _ensure_lxml_worker_started()

        # A fresh queue per call, never shared - see the module docstring.
        # Concurrent callers (e.g. several converter threads validating at
        # nearly the same moment) each wait on their OWN response queue, so
        # one caller can never receive a different caller's result.
        response_q: "queue.Queue" = queue.Queue(maxsize=1)
        _LXML_JOBS.put((self, xml_bytes, response_q))

        try:
            ok, payload = response_q.get(timeout=_LXML_WORKER_RESPONSE_TIMEOUT)
        except queue.Empty:
            raise RuntimeError(
                "The persistent lxml validation worker thread did not "
                f"respond within {_LXML_WORKER_RESPONSE_TIMEOUT}s. This "
                "should never happen in normal operation - see the module "
                "docstring's 'PERSISTENT LXML WORKER THREAD' section and "
                "check whether _lxml_worker_loop() is still running."
            )

        if ok:
            return payload
        raise payload

    def generate_package_metadata(
        self,
        title: str,
        abstract: str,
        poc: str,
        org: str,
        nation: str,
        security: str,
        language: str,
        topic_category: str,
        ref_date: str,
        data_quality: Optional[str] = None,
        lineage: Optional[str] = None,
        releasability: Optional[str] = None,
    ) -> str:
        """
        Generate package-level ISO 19115 metadata XML.

        Creates metadata describing the entire GeoPackage dataset,
        including contact information, classification, and data quality.

        Args:
            title: Dataset title
            abstract: Dataset description
            poc: Point of contact name
            org: Organization name
            nation: ISO 3166-1 alpha-3 nation code
            security: Security classification (UNCLASSIFIED, CONFIDENTIAL, SECRET, etc.)
            language: ISO 639-2 language code
            topic_category: ISO 19115 topic category
            ref_date: Reference date (YYYY-MM-DD)
            data_quality: Optional data quality statement
            lineage: Optional lineage/source information

        Returns:
            XML string of package-level metadata

        Raises:
            ValueError: If required fields are invalid or XML generation fails
        """
        try:
            # Generate unique file identifier
            file_id = str(uuid.uuid4())
            now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            # Escape XML special characters in user inputs
            t = saxutils.escape(title)
            a = saxutils.escape(abstract)
            p = saxutils.escape(poc)
            o = saxutils.escape(org)
            n = saxutils.escape(nation)
            sec_label = saxutils.escape(security)
            sec_code = SECURITY_CODE_MAP.get(security, "unclassified")
            lng = saxutils.escape(language)
            tc = saxutils.escape(topic_category)
            rd = saxutils.escape(ref_date)
            ni = saxutils.escape(now_iso)

            # Build XML (ISO 19115 with DGIWG extensions)
            xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco"
                 xmlns:gml="http://www.opengis.net/gml/3.2"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://www.isotc211.org/2005/gmd http://schemas.opengis.net/csw/2.0.2/profiles/apiso/1.0.0/apiso.xsd">

  <!-- File Identifier (UUID) -->
  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>

  <!-- Language of metadata -->
  <gmd:language>
    <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
  </gmd:language>

  <!-- Character set (UTF-8) -->
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>

  <!-- Hierarchy level (dataset) -->
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>

  <!-- Point of contact (individual responsible) -->
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:individualName><gco:CharacterString>{p}</gco:CharacterString></gmd:individualName>
      <gmd:organisationName><gco:CharacterString>{o}</gco:CharacterString></gmd:organisationName>
      <gmd:contactInfo>
        <gmd:CI_Contact>
          <gmd:address>
            <gmd:CI_Address>
              <gmd:country><gco:CharacterString>{n}</gco:CharacterString></gmd:country>
            </gmd:CI_Address>
          </gmd:address>
        </gmd:CI_Contact>
      </gmd:contactInfo>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>

  <!-- Metadata creation date -->
  <gmd:dateStamp>
    <gco:DateTime>{ni}</gco:DateTime>
  </gmd:dateStamp>

  <!-- Metadata standard (DGIWG DMF) -->
  <gmd:metadataStandardName><gco:CharacterString>DGIWG Metadata Foundation (DMF)</gco:CharacterString></gmd:metadataStandardName>
  <gmd:metadataStandardVersion><gco:CharacterString>2.0</gco:CharacterString></gmd:metadataStandardVersion>

  <!-- Data Identification -->
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>

      <!-- Citation (title and date) -->
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>{t}</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>{rd}</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="publication">publication</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>

      <!-- Abstract -->
      <gmd:abstract><gco:CharacterString>{a}</gco:CharacterString></gmd:abstract>

      <!-- Language -->
      <gmd:language>
        <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
      </gmd:language>

      <!-- Character set -->
      <gmd:characterSet>
        <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
      </gmd:characterSet>

      <!-- Topic category -->
      <gmd:topicCategory>
        <gmd:MD_TopicCategoryCode>{tc}</gmd:MD_TopicCategoryCode>
      </gmd:topicCategory>

    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>

  <!-- Data quality -->
  <!-- COMPLIANCE-7: ISO 19139 XSD sequence requires dataQualityInfo BEFORE
       metadataConstraints at the MD_Metadata level. -->
  <gmd:dataQualityInfo>
    <gmd:DQ_DataQuality>
      <gmd:scope>
        <gmd:DQ_Scope>
          <gmd:level>
            <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
          </gmd:level>
        </gmd:DQ_Scope>
      </gmd:scope>
      {f'<gmd:report><gmd:DQ_DomainConsistency><gmd:result><gmd:DQ_ConformanceResult><gmd:explanation><gco:CharacterString>{saxutils.escape(data_quality)}</gco:CharacterString></gmd:explanation><gmd:pass><gco:Boolean>true</gco:Boolean></gmd:pass></gmd:DQ_ConformanceResult></gmd:result></gmd:DQ_DomainConsistency></gmd:report>' if data_quality else ''}
      {f'<gmd:lineage><gmd:LI_Lineage><gmd:statement><gco:CharacterString>{saxutils.escape(lineage)}</gco:CharacterString></gmd:statement></gmd:LI_Lineage></gmd:lineage>' if lineage else ''}
    </gmd:DQ_DataQuality>
  </gmd:dataQualityInfo>

  <!-- Security constraints (DGIWG-required) -->
  <gmd:metadataConstraints>
    <gmd:MD_SecurityConstraints>
      <gmd:classification>
        <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
      </gmd:classification>
      <gmd:classificationSystem><gco:CharacterString>NATO/DGIWG</gco:CharacterString></gmd:classificationSystem>
      <gmd:handlingDescription><gco:CharacterString>Producer Nation: {n}{f". Releasable to: {saxutils.escape(releasability)}" if releasability else ""}</gco:CharacterString></gmd:handlingDescription>
    </gmd:MD_SecurityConstraints>
  </gmd:metadataConstraints>

</gmd:MD_Metadata>'''

            # Step 1: Validate XML is well-formed (basic check)
            # stdlib expat - independent parser per call, no libxml2 state.
            ET.fromstring(xml_str)

            # Step 2: Validate against ISO 19115 schema (full compliance check)
            try:
                self.validate_schema(xml_str)
            except ValueError as schema_error:
                logger.warning(f"Schema validation warning: {schema_error}")
                # Don't fail - schema validation is optional but logged

            logger.info(f"Generated package metadata (UUID: {file_id})")
            return xml_str

        except Exception as e:
            raise ValueError(f"Error generating metadata: {e}")

    def generate_dmf_metadata(
        self,
        title: str,
        abstract: str,
        org: str,
        nation: str,
        security: str,
        language: str,
        ref_date: str,
        releasability: Optional[str] = None,
    ) -> str:
        """
        Generate a DGIWG Metadata Foundation (DMF) 2.0 metadata record
        (v0.27.0, DGIWG GeoPackage Profile Req 18).

        The DGIWG GeoPackage Validator only awards Req 18 a full PASS when
        gpkg_metadata contains a row whose md_standard_uri is a DGIWG DMF URI
        and whose XML satisfies the DMF structural rules:

        - root gmd:MD_Metadata containing ONLY the DMF-recognised children
          (fileIdentifier, language, characterSet, hierarchyLevel, contact,
          dateStamp, identificationInfo and the optional constraint blocks);
          elements such as metadataStandardName are NOT permitted
        - fileIdentifier: UUID
        - language: 3-letter ISO 639-2 code
        - characterSet: valid MD_CharacterSetCode (utf8)
        - hierarchyLevel: valid MD_ScopeCode (dataset)
        - contact: organisationName + CI_RoleCode
        - dateStamp: ISO 8601 date

        Args:
            title: Dataset title
            abstract: Dataset description
            org: Responsible organisation
            nation: ISO 3166-1 alpha-3 producer nation code
            security: Security classification label
            language: ISO 639-2 language code
            ref_date: Reference date (YYYY-MM-DD)
            releasability: Optional releasability statement
                (e.g. "NATO" or "USA, GBR, CAN")

        Returns:
            XML string of the DMF metadata record
        """
        try:
            file_id = str(uuid.uuid4())
            date_stamp = datetime.utcnow().strftime("%Y-%m-%d")

            t = saxutils.escape(title)
            a = saxutils.escape(abstract)
            o = saxutils.escape(org)
            n = saxutils.escape(nation)
            sec_label = saxutils.escape(security)
            sec_code = SECURITY_CODE_MAP.get(security, "unclassified")
            lng = saxutils.escape((language or "eng").lower())
            rd = saxutils.escape(ref_date or date_stamp)

            releasability_block = ""
            if releasability:
                rel = saxutils.escape(releasability)
                releasability_block = f"""
      <gmd:resourceConstraints>
        <gmd:MD_LegalConstraints>
          <gmd:useLimitation><gco:CharacterString>Releasable to: {rel}</gco:CharacterString></gmd:useLimitation>
        </gmd:MD_LegalConstraints>
      </gmd:resourceConstraints>"""

            xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco">
  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>
  <gmd:language>
    <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
  </gmd:language>
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:organisationName><gco:CharacterString>{o}</gco:CharacterString></gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>
  <gmd:dateStamp>
    <gco:Date>{date_stamp}</gco:Date>
  </gmd:dateStamp>
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>{t}</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>{rd}</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="publication">publication</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>
      <gmd:abstract><gco:CharacterString>{a}</gco:CharacterString></gmd:abstract>{releasability_block}
      <gmd:resourceConstraints>
        <gmd:MD_SecurityConstraints>
          <gmd:classification>
            <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
          </gmd:classification>
          <gmd:classificationSystem><gco:CharacterString>NATO/DGIWG</gco:CharacterString></gmd:classificationSystem>
          <gmd:handlingDescription><gco:CharacterString>Producer Nation: {n}</gco:CharacterString></gmd:handlingDescription>
        </gmd:MD_SecurityConstraints>
      </gmd:resourceConstraints>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>
</gmd:MD_Metadata>'''

            # Well-formedness check (stdlib expat, no libxml2 state)
            ET.fromstring(xml_str)
            logger.info(f"Generated DMF metadata record (UUID: {file_id})")
            return xml_str

        except Exception as e:
            raise ValueError(f"Error generating DMF metadata: {e}")

    def generate_layer_metadata(
        self,
        layer_name: str,
        poc: str,
        org: str,
        nation: str,
        security: str,
        language: str,
        ref_date: str,
    ) -> str:
        """
        Generate layer-level ISO 19115 metadata XML.

        Creates metadata for individual feature layer, linked to package-level
        metadata via parent reference.

        Args:
            layer_name: Feature layer name
            poc: Point of contact
            org: Organization
            nation: Nation code
            security: Security classification
            language: Language code
            ref_date: Reference date

        Returns:
            XML string of layer metadata
        """
        try:
            file_id = str(uuid.uuid4())
            now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            ln = saxutils.escape(layer_name.replace("_", " ").title())
            p = saxutils.escape(poc)
            o = saxutils.escape(org)
            n = saxutils.escape(nation)
            sec_label = saxutils.escape(security)
            sec_code = SECURITY_CODE_MAP.get(security, "unclassified")
            lng = saxutils.escape(language)
            rd = saxutils.escape(ref_date)

            xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco">

  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>

  <gmd:language>
    <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
  </gmd:language>

  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>

  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>

  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:individualName><gco:CharacterString>{p}</gco:CharacterString></gmd:individualName>
      <gmd:organisationName><gco:CharacterString>{o}</gco:CharacterString></gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>

  <gmd:dateStamp>
    <gco:DateTime>{now_iso}</gco:DateTime>
  </gmd:dateStamp>

  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>{ln}</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>{rd}</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="publication">publication</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>
      <!-- COMPLIANCE-10: gmd:abstract is mandatory (minOccurs=1) in
           MD_DataIdentification per ISO 19139 XSD. Use a generated value
           derived from the layer name when no explicit abstract is given. -->
      <gmd:abstract><gco:CharacterString>Feature layer: {ln}</gco:CharacterString></gmd:abstract>
      <gmd:language>
        <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
      </gmd:language>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>

  <!-- COMPLIANCE-8: dataQualityInfo must precede metadataConstraints per
       ISO 19139 XSD sequence.  Layer metadata has no quality report so an
       empty DQ_DataQuality element is omitted; constraints come last. -->
  <gmd:metadataConstraints>
    <gmd:MD_SecurityConstraints>
      <gmd:classification>
        <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
      </gmd:classification>
    </gmd:MD_SecurityConstraints>
  </gmd:metadataConstraints>

</gmd:MD_Metadata>'''

            # Step 1: Validate XML is well-formed (stdlib expat)
            ET.fromstring(xml_str)

            # Step 2: Validate against ISO 19115 schema
            try:
                self.validate_schema(xml_str)
            except ValueError as schema_error:
                logger.warning(f"Layer metadata schema validation warning: {schema_error}")
                # Don't fail - schema validation is optional but logged

            logger.info(f"Generated layer metadata for '{layer_name}' (UUID: {file_id})")
            return xml_str

        except Exception as e:
            raise ValueError(f"Error generating layer metadata: {e}")
