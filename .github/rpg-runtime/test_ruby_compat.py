"""Run the actual legacy Ruby compatibility code installed by the core patch."""

import importlib.util
from pathlib import Path
import re
import subprocess
import unittest


RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]


def module():
    spec = importlib.util.spec_from_file_location("ruby_compat", RECIPE / "patch-ruby-compat.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class RubyCompatTests(unittest.TestCase):
    def test_unknown_or_already_patched_sources_fail_closed(self):
        patch = module()
        source = (ROOT / "mkxp-z/binding-sandbox/binding-sandbox.cpp").read_text()
        for invalid in (source.replace(patch.ANCHOR, ""), patch.patch_binding(source)):
            with self.assertRaisesRegex(ValueError, "MKXP_RUBY_COMPAT_SOURCE_INVALID"):
                patch.patch_binding(invalid)

    def test_removed_taint_methods_keep_receiver_identity_and_false_queries(self):
        source = (ROOT / "mkxp-z/binding-sandbox/binding-sandbox.cpp").read_text()
        patched = module().patch_binding(source)
        scripts = re.findall(r'R"ruby\((.*?)\)ruby"', patched, re.S)
        setup = """
          methods = [:taint, :untaint, :trust, :untrust, :tainted?, :untrusted?]
          methods.each { |name| Object.send(:undef_method, name) if Object.method_defined?(name) }
        """
        checks = """
          [Object.new, Class.new, 'text', 'frozen'.freeze, 1, nil, true, false].each do |object|
            [:taint, :untaint, :trust, :untrust].each do |name|
              raise name.to_s unless object.public_send(name).equal?(object)
              begin
                object.public_send(name, 1)
                raise 'wrong arity accepted'
              rescue ArgumentError
              end
            end
            raise 'tainted' unless object.tainted? == false
            raise 'untrusted' unless object.untrusted? == false
          end
          class SaveScene; end
          raise 'scene identity' unless SaveScene.untaint.equal?(SaveScene)
        """
        result = subprocess.run(["ruby", "-e", setup + "\n".join(scripts) + checks],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
