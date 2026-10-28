# Contributing to Serpentine

Thanks for your interest! Serpentine is a young, `0.x` project, so bug reports with a small
reproducer are the most valuable contribution right now. Questions and ideas are welcome in
[GitHub Discussions](https://github.com/avijitbhuin21/Serpentine/discussions).

## Reporting bugs

Open an issue with the **Bug report** template. Please include:

- `serp --version` output, your OS, Python version and `rustc --version`;
- the backend (`--backend llvm` is the default, `--backend rust` the oracle) and whether it was a
  `--debug` build;
- the smallest `.py` file that shows the problem, with the CPython output and the native output.

A program that `serp check` accepts but that behaves differently natively than under CPython is
a top-priority bug (it breaks the dual-execution guarantee). **Security issues** go through
private vulnerability reporting instead, see [SECURITY.md](SECURITY.md).

## Development setup

```console
git clone https://github.com/avijitbhuin21/Serpentine
cd Serpentine
python -m venv .venv            # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ./shim -e "./compiler"
```

You also need a Rust toolchain ([rustup.rs](https://rustup.rs)); on Windows the MSVC C++ Build
Tools as well.

## Running the tests

All tools live in `tools/`; [docs/guides/testing.md](docs/guides/testing.md) describes every one.
The core loop before opening a pull request:

```console
python tools/run_differential_tests.py     # accept corpus: CPython vs Backend A
python tools/run_llvm_differential.py      # accept corpus: CPython vs Backend B
python tools/run_reject_serp.py            # reject corpus: exact SE codes
python tools/run_lib_tests.py              # every libs/*/tests file on all three runtimes
python tools/run_rustc_agreement.py        # borrow checker vs rustc (0 disagreements)
```

## Making changes

- **Language changes** follow [docs/spec.md](docs/spec.md) and [docs/DECISIONS.md](docs/DECISIONS.md).
  A new accepted feature needs an accept test (`tests/accept/NNN_*.py`) that prints its results,
  so CPython and both backends can be compared byte for byte. A new rejection needs a reject test
  (`tests/reject/rNNN_*.py`) annotated with its SE code.
- **Both backends** must agree: a codegen change in `rustgen.py` usually needs the matching change
  in `llvmgen.py`, and new runtime functions go into `prelude.rs`, `rt.rs`, `llvmgen.RT_SIGS` and
  (for library primitives) `rtlib.py`.
- **Libraries** live in `libs/serp-<name>/` with `src/`, `tests/`, `serp.toml` and `pyproject.toml`.
  Every module in `src/` must be listed in the `py-modules` of `pyproject.toml`.
- Keep the [CHANGELOG](CHANGELOG.md) and [docs/libraries.md](docs/libraries.md) current.

## Pull requests

Keep pull requests focused, describe what changed and how you tested it (the PR template has a
checklist), and expect CI to run the suites on Windows, Linux and macOS.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Contributions are
licensed under the project's [MIT License](LICENSE).
