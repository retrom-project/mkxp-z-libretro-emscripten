"""Restore legacy Ruby no-op taint APIs in the RGSS sandbox."""

import argparse
from pathlib import Path


ANCHOR = '        SANDBOX_AWAIT(rb_define_method, sb()->rb_mKernel(), "type", (VALUE (*)(ANYARGS))legacy_kernel_type, 0);\n'
COMPATIBILITY = '''
        // Ruby 3.2 removed the taint APIs used by older RGSS scripts. Preserve
        // Ruby 2.7-3.1's no-op semantics inside the existing sandbox boundary.
        SANDBOX_AWAIT(rb_eval_string, R"ruby(
class Object
  def taint; self; end
  alias untaint taint
  alias trust taint
  alias untrust taint
  def tainted?; false; end
  alias untrusted? tainted?
end
)ruby");
'''


def patch_binding(source: str) -> str:
    if source.count(ANCHOR) != 1 or COMPATIBILITY in source:
        raise ValueError("MKXP_RUBY_COMPAT_SOURCE_INVALID")
    return source.replace(ANCHOR, ANCHOR + COMPATIBILITY)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    root = parser.parse_args().source
    binding = root / "mkxp-z/binding-sandbox/binding-sandbox.cpp"
    binding.write_text(patch_binding(binding.read_text()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
