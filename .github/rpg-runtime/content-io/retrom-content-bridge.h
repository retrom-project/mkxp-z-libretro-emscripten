#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int32_t retrom_content_read_bridge(const char* file_id, uint32_t offset_low,
  uint32_t offset_high, uint32_t length, uint32_t timeout_ms, uintptr_t destination);
double retrom_content_get_size(const char* file_id);
int retrom_content_mount_manifest(const char* manifest_path, const char* mount_path);
#ifdef __cplusplus
}
#endif
