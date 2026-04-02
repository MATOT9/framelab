#ifndef FRAMELAB_NATIVE_LOADERS_FILE_MAP_H
#define FRAMELAB_NATIVE_LOADERS_FILE_MAP_H

#include <stddef.h>
#include <stdint.h>

#include "framelab_native/common/status.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/types.h>
#endif

typedef struct FramelabMappedFile {
    const uint8_t *data;
    size_t size;
#ifdef _WIN32
    HANDLE file_handle;
    HANDLE mapping_handle;
#else
    int fd;
#endif
} FramelabMappedFile;

int framelab_file_mapping_supported(void);

FramelabStatus framelab_file_map_readonly(const char *path, FramelabMappedFile *mapped);
void framelab_file_map_close(FramelabMappedFile *mapped);

#endif
