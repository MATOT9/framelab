#ifndef FRAMELAB_NATIVE_API_PYTHON_BRIDGE_H
#define FRAMELAB_NATIVE_API_PYTHON_BRIDGE_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#define PY_ARRAY_UNIQUE_SYMBOL FRAMELAB_NUMPY_API
#ifndef FRAMELAB_NUMPY_API_IMPORT
#define NO_IMPORT_ARRAY
#endif

#define NPY_NO_DEPRECATED_API NPY_1_20_API_VERSION
#include <numpy/arrayobject.h>

#ifdef _PyCFunction_CAST
#define FRAMELAB_PY_CFUNCTION_CAST(func) _PyCFunction_CAST(func)
#else
#define FRAMELAB_PY_CFUNCTION_CAST(func) ((PyCFunction)(void (*)(void))(func))
#endif

#include "framelab_native/common/types.h"
#include "framelab_native/common/status.h"

#ifdef __cplusplus
extern "C" {
#endif

int framelab_py_image_view_from_object(PyObject *obj,
                                       const char *arg_name,
                                       FramelabImageView *view,
                                       PyArrayObject **array_out);

int framelab_py_optional_image_view_from_object(PyObject *obj,
                                                const char *arg_name,
                                                FramelabImageView *view,
                                                PyArrayObject **array_out,
                                                int *present_out);

int framelab_py_parse_roi_rect(PyObject *obj,
                               npy_intp width,
                               npy_intp height,
                               FramelabRoi *roi_out);

PyObject *framelab_py_status_error(FramelabStatus status, const char *context);

#ifdef __cplusplus
}
#endif

#endif
