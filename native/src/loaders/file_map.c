#include "file_map.h"

#include <stdlib.h>
#include <string.h>

#ifdef _WIN32

static wchar_t *framelab_utf8_to_wide(const char *path) {
    int wide_chars;
    wchar_t *wide = NULL;

    if (path == NULL) {
        return NULL;
    }
    wide_chars = MultiByteToWideChar(CP_UTF8, 0, path, -1, NULL, 0);
    if (wide_chars <= 0) {
        return NULL;
    }
    wide = (wchar_t *)malloc((size_t)wide_chars * sizeof(wchar_t));
    if (wide == NULL) {
        return NULL;
    }
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wide, wide_chars) <= 0) {
        free(wide);
        return NULL;
    }
    return wide;
}

int framelab_file_mapping_supported(void) {
    return 1;
}

FramelabStatus framelab_file_map_readonly(const char *path, FramelabMappedFile *mapped) {
    LARGE_INTEGER size_bytes;
    wchar_t *wide = NULL;

    if (path == NULL || mapped == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    memset(mapped, 0, sizeof(*mapped));
    mapped->file_handle = INVALID_HANDLE_VALUE;
    wide = framelab_utf8_to_wide(path);
    if (wide == NULL) {
        return FRAMELAB_STATUS_IO_ERROR;
    }
    mapped->file_handle = CreateFileW(
        wide,
        GENERIC_READ,
        FILE_SHARE_READ,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    free(wide);
    if (mapped->file_handle == INVALID_HANDLE_VALUE) {
        return FRAMELAB_STATUS_IO_ERROR;
    }
    if (!GetFileSizeEx(mapped->file_handle, &size_bytes)) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    if (size_bytes.QuadPart < 0) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    mapped->mapping_handle = CreateFileMappingW(
        mapped->file_handle,
        NULL,
        PAGE_READONLY,
        0,
        0,
        NULL);
    if (mapped->mapping_handle == NULL) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    mapped->data = (const uint8_t *)MapViewOfFile(
        mapped->mapping_handle,
        FILE_MAP_READ,
        0,
        0,
        0);
    if (mapped->data == NULL) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    mapped->size = (size_t)size_bytes.QuadPart;
    return FRAMELAB_STATUS_OK;
}

void framelab_file_map_close(FramelabMappedFile *mapped) {
    if (mapped == NULL) {
        return;
    }
    if (mapped->data != NULL) {
        UnmapViewOfFile(mapped->data);
    }
    if (mapped->mapping_handle != NULL) {
        CloseHandle(mapped->mapping_handle);
    }
    if (mapped->file_handle != NULL && mapped->file_handle != INVALID_HANDLE_VALUE) {
        CloseHandle(mapped->file_handle);
    }
    memset(mapped, 0, sizeof(*mapped));
    mapped->file_handle = INVALID_HANDLE_VALUE;
}

#else

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

int framelab_file_mapping_supported(void) {
    return 1;
}

FramelabStatus framelab_file_map_readonly(const char *path, FramelabMappedFile *mapped) {
    struct stat st;
    void *view = NULL;

    if (path == NULL || mapped == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    memset(mapped, 0, sizeof(*mapped));
    mapped->fd = -1;
    mapped->fd = open(path, O_RDONLY);
    if (mapped->fd < 0) {
        return FRAMELAB_STATUS_IO_ERROR;
    }
    if (fstat(mapped->fd, &st) != 0) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    if (st.st_size < 0) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    view = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, mapped->fd, 0);
    if (view == MAP_FAILED) {
        framelab_file_map_close(mapped);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    mapped->data = (const uint8_t *)view;
    mapped->size = (size_t)st.st_size;
    return FRAMELAB_STATUS_OK;
}

void framelab_file_map_close(FramelabMappedFile *mapped) {
    if (mapped == NULL) {
        return;
    }
    if (mapped->data != NULL && mapped->size > 0U) {
        munmap((void *)mapped->data, mapped->size);
    }
    if (mapped->fd >= 0) {
        close(mapped->fd);
    }
    memset(mapped, 0, sizeof(*mapped));
    mapped->fd = -1;
}

#endif
