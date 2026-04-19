#include "python_bridge.h"

#include <stddef.h>
#include <stdint.h>

static int framelab_sample_type_from_numpy(int typenum, FramelabSampleType *sample_type) {
    switch (typenum) {
        case NPY_UINT8:
            *sample_type = FRAMELAB_SAMPLE_U8;
            return 1;
        case NPY_UINT16:
            *sample_type = FRAMELAB_SAMPLE_U16;
            return 1;
        case NPY_FLOAT32:
            *sample_type = FRAMELAB_SAMPLE_F32;
            return 1;
        case NPY_FLOAT64:
            *sample_type = FRAMELAB_SAMPLE_F64;
            return 1;
        default:
            return 0;
    }
}

int framelab_py_image_view_from_object(
    PyObject *obj,
    const char *arg_name,
    FramelabImageView *view,
    PyArrayObject **array_out
) {
    PyArrayObject *array = NULL;
    FramelabSampleType sample_type;
    int typenum;
    npy_intp width;
    npy_intp height;
    npy_intp itemsize;
    npy_intp stride_row;
    npy_intp stride_col;

    if (obj == NULL || view == NULL || array_out == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "internal argument error");
        return 0;
    }

    array = (PyArrayObject *)PyArray_FromAny(
        obj,
        NULL,
        2,
        2,
        NPY_ARRAY_ALIGNED | NPY_ARRAY_NOTSWAPPED,
        NULL
    );
    if (array == NULL) {
        return 0;
    }

    typenum = PyArray_TYPE(array);
    if (!framelab_sample_type_from_numpy(typenum, &sample_type)) {
        PyErr_Format(
            PyExc_TypeError,
            "%s must have dtype uint8, uint16, float32, or float64",
            arg_name
        );
        Py_DECREF(array);
        return 0;
    }

    if (PyArray_NDIM(array) != 2) {
        PyErr_Format(PyExc_ValueError, "%s must be a 2D array", arg_name);
        Py_DECREF(array);
        return 0;
    }

    height = PyArray_DIM(array, 0);
    width = PyArray_DIM(array, 1);
    if (height <= 0 || width <= 0) {
        PyErr_Format(PyExc_ValueError, "%s must have non-zero width and height", arg_name);
        Py_DECREF(array);
        return 0;
    }
    if (height > (npy_intp)UINT32_MAX || width > (npy_intp)UINT32_MAX) {
        PyErr_Format(PyExc_OverflowError, "%s is too large for native backend dimensions", arg_name);
        Py_DECREF(array);
        return 0;
    }

    itemsize = PyArray_ITEMSIZE(array);
    stride_row = PyArray_STRIDE(array, 0);
    stride_col = PyArray_STRIDE(array, 1);
    if (stride_row < 0 || stride_col < 0) {
        PyErr_Format(PyExc_ValueError, "%s must not use negative strides", arg_name);
        Py_DECREF(array);
        return 0;
    }
    if (stride_col != itemsize) {
        PyErr_Format(
            PyExc_ValueError,
            "%s must be contiguous within each row (expected column stride == itemsize)",
            arg_name
        );
        Py_DECREF(array);
        return 0;
    }
    if (stride_row < width * itemsize) {
        PyErr_Format(PyExc_ValueError, "%s row stride is smaller than one row of samples", arg_name);
        Py_DECREF(array);
        return 0;
    }
    if (stride_row > (npy_intp)UINT32_MAX) {
        PyErr_Format(PyExc_OverflowError, "%s row stride is too large for native backend", arg_name);
        Py_DECREF(array);
        return 0;
    }

    view->data = PyArray_DATA(array);
    view->width = (uint32_t)width;
    view->height = (uint32_t)height;
    view->stride_bytes = (uint32_t)stride_row;
    view->sample_type = sample_type;
    *array_out = array;
    return 1;
}

int framelab_py_optional_image_view_from_object(
    PyObject *obj,
    const char *arg_name,
    FramelabImageView *view,
    PyArrayObject **array_out,
    int *present_out
) {
    if (present_out == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "internal optional argument error");
        return 0;
    }
    if (obj == NULL || obj == Py_None) {
        *present_out = 0;
        if (array_out != NULL) {
            *array_out = NULL;
        }
        return 1;
    }
    *present_out = 1;
    return framelab_py_image_view_from_object(obj, arg_name, view, array_out);
}

static npy_intp normalize_slice_index(npy_intp index, npy_intp limit) {
    if (index < 0) {
        index += limit;
    }
    if (index < 0) {
        return 0;
    }
    if (index > limit) {
        return limit;
    }
    return index;
}

int framelab_py_parse_roi_rect(
    PyObject *obj,
    npy_intp width,
    npy_intp height,
    FramelabRoi *roi_out
) {
    PyObject *seq = NULL;
    PyObject *item = NULL;
    npy_intp values[4];
    Py_ssize_t i;

    if (obj == NULL || roi_out == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "internal ROI argument error");
        return 0;
    }

    seq = PySequence_Fast(obj, "roi_rect must be a 4-item iterable");
    if (seq == NULL) {
        return 0;
    }
    if (PySequence_Fast_GET_SIZE(seq) != 4) {
        PyErr_SetString(PyExc_ValueError, "roi_rect must contain exactly 4 integers");
        Py_DECREF(seq);
        return 0;
    }

    for (i = 0; i < 4; ++i) {
        item = PySequence_Fast_GET_ITEM(seq, i);
        values[i] = PyArray_PyIntAsIntp(item);
        if (PyErr_Occurred()) {
            Py_DECREF(seq);
            return 0;
        }
    }
    Py_DECREF(seq);

    values[0] = normalize_slice_index(values[0], width);
    values[2] = normalize_slice_index(values[2], width);
    values[1] = normalize_slice_index(values[1], height);
    values[3] = normalize_slice_index(values[3], height);
    if (values[2] < values[0]) {
        values[2] = values[0];
    }
    if (values[3] < values[1]) {
        values[3] = values[1];
    }

    roi_out->x0 = (int32_t)values[0];
    roi_out->y0 = (int32_t)values[1];
    roi_out->x1 = (int32_t)values[2];
    roi_out->y1 = (int32_t)values[3];
    return 1;
}

PyObject *framelab_py_status_error(FramelabStatus status, const char *context) {
    const char *prefix = context != NULL ? context : "FrameLab native backend error";
    const char *detail = framelab_status_string(status);

    switch (status) {
        case FRAMELAB_STATUS_INVALID_ARGUMENT:
        case FRAMELAB_STATUS_SIZE_MISMATCH:
        case FRAMELAB_STATUS_OUT_OF_RANGE:
            PyErr_Format(PyExc_ValueError, "%s: %s", prefix, detail);
            break;
        case FRAMELAB_STATUS_ALLOC_FAILED:
            PyErr_Format(PyExc_MemoryError, "%s: %s", prefix, detail);
            break;
        case FRAMELAB_STATUS_IO_ERROR:
            PyErr_Format(PyExc_OSError, "%s: %s", prefix, detail);
            break;
        case FRAMELAB_STATUS_UNSUPPORTED_FORMAT:
        case FRAMELAB_STATUS_NOT_IMPLEMENTED:
            PyErr_Format(PyExc_NotImplementedError, "%s: %s", prefix, detail);
            break;
        default:
            PyErr_Format(PyExc_RuntimeError, "%s: %s", prefix, detail);
            break;
    }
    return NULL;
}
