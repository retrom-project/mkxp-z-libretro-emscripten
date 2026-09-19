/** Retrom content-io-v1: metadata and capability forwarding only; no transport or byte cache. */
addToLibrary({
  _wasmfs_create_fetch_backend_js__deps: [
    '$wasmFS$backends', '_wasmfs_fetch_get_file_url',
    'retrom_content_get_size', 'retrom_content_read_bridge', '$UTF8ToString',
  ],
  _wasmfs_create_fetch_backend_js: async function(backend) {
    wasmFS$backends[backend] = {
      allocFile: async () => {},
      freeFile: async () => {},
      write: async () => -{{{ cDefs.EROFS }}},
      getSize: async (file) => _retrom_content_get_size(__wasmfs_fetch_get_file_url(file)),
      read: async (file, buffer, length, offset) => {
        if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(length) || length < 0) {
          return -{{{ cDefs.EINVAL }}};
        }
        const id = __wasmfs_fetch_get_file_url(file);
        const size = _retrom_content_get_size(id);
        if (size < 0) {return -{{{ cDefs.ENOENT }}};}
        length = Math.min(length, Math.max(0, size - offset));
        offset = Math.min(offset, size);
        const deadline = performance.now() + 15000;
        let done = 0;
        // Even EOF/zero length traverses the bridge to enforce revocation.
        do {
          const count = Math.min(262144, length - done), at = offset + done;
          const timeout = Math.ceil(deadline - performance.now());
          if (timeout <= 0) {return -{{{ cDefs.ETIMEDOUT }}};}
          const result = _retrom_content_read_bridge(id, at % 4294967296, Math.floor(at / 4294967296),
            count, timeout, buffer + done);
          if (result < 0) {return result;}
          if (result !== count) {return -{{{ cDefs.EIO }}};}
          done += result;
        } while (done < length);
        return done;
      },
    };
  },
});
