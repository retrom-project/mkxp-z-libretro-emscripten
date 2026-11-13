# Minimal RGSS3 regression: a rescued native call leaves orphaned C++ bindings.
# Defining an alias reuses their old Ruby C stack slots before the next callback.
class RescuedNativeCall
  def original
    true
  end

  begin
    load_data("Data/nonexistent-probe.rvdata2")
    raise "The fixture's optional file must be absent"
  rescue Errno::ENOENT
    OPTIONAL_DATA = {}
  end

  alias copied original
end

raise "Alias failed" unless RescuedNativeCall.new.copied
sprite = Sprite.new
sprite.bitmap = Bitmap.new(320, 240)
sprite.bitmap.fill_rect(0, 0, 320, 240, Color.new(0, 255, 0))
loop do
  Graphics.update
  Input.update
end
