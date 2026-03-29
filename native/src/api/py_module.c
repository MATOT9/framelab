#include <stdint.h>
#include <string.h>

#define FRAMELAB_NUMPY_API_IMPORT
#include "python_bridge.h"
#include "framelab_native/common/pixel_formats.h"
#include "framelab_native/loaders/raw_loader.h"
#include "framelab_native/metrics/app_metrics.h"

static PyObject *build_static_metrics_result(const FramelabStaticScanResult *result) {
    PyObject *tuple_obj = PyTuple_New(2);
    PyObject *item0 = NULL;
    PyObject *item1 = NULL;
    if (tuple_obj == NULL) {
        return NULL;
    }
    item0 = PyLong_FromLongLong((long long)result->min_non_zero);
    item1 = PyLong_FromLongLong((long long)result->max_pixel);
    if (item0 == NULL || item1 == NULL) {
        Py_XDECREF(item0);
        Py_XDECREF(item1);
        Py_DECREF(tuple_obj);
        return NULL;
    }
    PyTuple_SET_ITEM(tuple_obj, 0, item0);
    PyTuple_SET_ITEM(tuple_obj, 1, item1);
    return tuple_obj;
}

static PyObject *build_dynamic_metrics_result(const FramelabDynamicMetricsResult *result,
                                              int include_topk) {
    PyObject *dict_obj = PyDict_New();
    PyObject *value = NULL;
    if (dict_obj == NULL) {
        return NULL;
    }

    value = PyLong_FromUnsignedLongLong((unsigned long long)result->threshold_count);
    if (value == NULL || PyDict_SetItemString(dict_obj, "sat_count", value) < 0) goto error;
    Py_DECREF(value); value = NULL;

    value = PyLong_FromLongLong((long long)result->min_non_zero);
    if (value == NULL || PyDict_SetItemString(dict_obj, "min_non_zero", value) < 0) goto error;
    Py_DECREF(value); value = NULL;

    value = PyLong_FromLongLong((long long)result->max_pixel);
    if (value == NULL || PyDict_SetItemString(dict_obj, "max_pixel", value) < 0) goto error;
    Py_DECREF(value); value = NULL;

    if (include_topk) {
        value = PyFloat_FromDouble(result->topk_mean);
        if (value == NULL || PyDict_SetItemString(dict_obj, "avg_topk", value) < 0) goto error;
        Py_DECREF(value); value = NULL;

        value = PyFloat_FromDouble(result->topk_stddev);
        if (value == NULL || PyDict_SetItemString(dict_obj, "avg_topk_std", value) < 0) goto error;
        Py_DECREF(value); value = NULL;

        value = PyFloat_FromDouble(result->topk_sem);
        if (value == NULL || PyDict_SetItemString(dict_obj, "avg_topk_sem", value) < 0) goto error;
        Py_DECREF(value); value = NULL;
    } else {
        Py_INCREF(Py_None);
        if (PyDict_SetItemString(dict_obj, "avg_topk", Py_None) < 0) goto error_none;
        if (PyDict_SetItemString(dict_obj, "avg_topk_std", Py_None) < 0) goto error_none;
        if (PyDict_SetItemString(dict_obj, "avg_topk_sem", Py_None) < 0) goto error_none;
        Py_DECREF(Py_None);
    }

    return dict_obj;

error_none:
    Py_DECREF(Py_None);
error:
    Py_XDECREF(value);
    Py_DECREF(dict_obj);
    return NULL;
}

static PyObject *build_roi_metrics_result(const FramelabRoiMetricsResult *result) {
    PyObject *tuple_obj = PyTuple_New(4);
    PyObject *item0 = NULL;
    PyObject *item1 = NULL;
    PyObject *item2 = NULL;
    PyObject *item3 = NULL;
    if (tuple_obj == NULL) {
        return NULL;
    }
    item0 = PyFloat_FromDouble(result->roi_max);
    item1 = PyFloat_FromDouble(result->roi_mean);
    item2 = PyFloat_FromDouble(result->roi_stddev);
    item3 = PyFloat_FromDouble(result->roi_sem);
    if (item0 == NULL || item1 == NULL || item2 == NULL || item3 == NULL) {
        Py_XDECREF(item0);
        Py_XDECREF(item1);
        Py_XDECREF(item2);
        Py_XDECREF(item3);
        Py_DECREF(tuple_obj);
        return NULL;
    }
    PyTuple_SET_ITEM(tuple_obj, 0, item0);
    PyTuple_SET_ITEM(tuple_obj, 1, item1);
    PyTuple_SET_ITEM(tuple_obj, 2, item2);
    PyTuple_SET_ITEM(tuple_obj, 3, item3);
    return tuple_obj;
}

static PyObject *py_compute_static_metrics(PyObject *self, PyObject *args) {
    PyObject *image_obj = NULL;
    PyArrayObject *image_array = NULL;
    FramelabImageView image_view;
    FramelabStaticScanParams params;
    FramelabStaticScanResult result;
    FramelabStatus status;
    PyObject *ret = NULL;
    (void)self;

    if (!PyArg_ParseTuple(args, "O:compute_static_metrics", &image_obj)) {
        return NULL;
    }
    if (!framelab_py_image_view_from_object(image_obj, "image", &image_view, &image_array)) {
        return NULL;
    }

    params.image = image_view;
    Py_BEGIN_ALLOW_THREADS
    status = framelab_compute_static_scan(&params, &result);
    Py_END_ALLOW_THREADS

    if (status != FRAMELAB_STATUS_OK) {
        Py_DECREF(image_array);
        return framelab_py_status_error(status, "compute_static_metrics failed");
    }

    ret = build_static_metrics_result(&result);
    Py_DECREF(image_array);
    return ret;
}

static PyObject *py_compute_dynamic_metrics(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *kwlist[] = {
        "image",
        "threshold_value",
        "mode",
        "avg_count_value",
        "background",
        "clip_negative",
        NULL
    };
    PyObject *image_obj = NULL;
    PyObject *background_obj = Py_None;
    const char *mode = "none";
    double threshold_value = 0.0;
    unsigned long avg_count_value = 1UL;
    int clip_negative = 1;
    PyArrayObject *image_array = NULL;
    PyArrayObject *background_array = NULL;
    FramelabImageView image_view;
    FramelabImageView background_view;
    int background_present = 0;
    FramelabDynamicMetricsParams params;
    FramelabDynamicMetricsResult result;
    FramelabStatus status;
    PyObject *ret = NULL;
    (void)self;

    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "Od|skOp:compute_dynamic_metrics",
            kwlist,
            &image_obj,
            &threshold_value,
            &mode,
            &avg_count_value,
            &background_obj,
            &clip_negative)) {
        return NULL;
    }
    if (!framelab_py_image_view_from_object(image_obj, "image", &image_view, &image_array)) {
        return NULL;
    }
    if (!framelab_py_optional_image_view_from_object(
            background_obj,
            "background",
            &background_view,
            &background_array,
            &background_present)) {
        Py_DECREF(image_array);
        return NULL;
    }

    memset(&params, 0, sizeof(params));
    params.image = image_view;
    params.background = background_present ? &background_view : NULL;
    params.background_mode = background_present
        ? (clip_negative ? FRAMELAB_BG_SUBTRACT_CLAMP_ZERO : FRAMELAB_BG_SUBTRACT)
        : FRAMELAB_BG_NONE;
    params.use_threshold = 1;
    params.threshold = threshold_value;
    if (strcmp(mode, "none") == 0) {
        params.use_topk = 0;
        params.topk_count = 0U;
    } else if (strcmp(mode, "topk") == 0) {
        params.use_topk = 1;
        params.topk_count = avg_count_value > (unsigned long)UINT32_MAX
            ? UINT32_MAX
            : (uint32_t)avg_count_value;
    } else {
        Py_DECREF(image_array);
        Py_XDECREF(background_array);
        PyErr_SetString(PyExc_ValueError, "mode must be 'none' or 'topk'");
        return NULL;
    }

    Py_BEGIN_ALLOW_THREADS
    status = framelab_compute_dynamic_metrics(&params, &result);
    Py_END_ALLOW_THREADS

    if (status != FRAMELAB_STATUS_OK) {
        Py_DECREF(image_array);
        Py_XDECREF(background_array);
        return framelab_py_status_error(status, "compute_dynamic_metrics failed");
    }

    ret = build_dynamic_metrics_result(&result, params.use_topk);
    Py_DECREF(image_array);
    Py_XDECREF(background_array);
    return ret;
}

static PyObject *py_compute_roi_metrics(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *kwlist[] = {"image", "roi_rect", "background", "clip_negative", NULL};
    PyObject *image_obj = NULL;
    PyObject *roi_obj = NULL;
    PyObject *background_obj = Py_None;
    int clip_negative = 1;
    PyArrayObject *image_array = NULL;
    PyArrayObject *background_array = NULL;
    FramelabImageView image_view;
    FramelabImageView background_view;
    FramelabRoi roi;
    int background_present = 0;
    FramelabRoiMetricsParams params;
    FramelabRoiMetricsResult result;
    FramelabStatus status;
    PyObject *ret = NULL;
    (void)self;

    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "OO|Op:compute_roi_metrics",
            kwlist,
            &image_obj,
            &roi_obj,
            &background_obj,
            &clip_negative)) {
        return NULL;
    }
    if (!framelab_py_image_view_from_object(image_obj, "image", &image_view, &image_array)) {
        return NULL;
    }
    if (!framelab_py_optional_image_view_from_object(
            background_obj,
            "background",
            &background_view,
            &background_array,
            &background_present)) {
        Py_DECREF(image_array);
        return NULL;
    }
    if (!framelab_py_parse_roi_rect(roi_obj, (npy_intp)image_view.width, (npy_intp)image_view.height, &roi)) {
        Py_DECREF(image_array);
        Py_XDECREF(background_array);
        return NULL;
    }

    memset(&params, 0, sizeof(params));
    params.image = image_view;
    params.background = background_present ? &background_view : NULL;
    params.background_mode = background_present
        ? (clip_negative ? FRAMELAB_BG_SUBTRACT_CLAMP_ZERO : FRAMELAB_BG_SUBTRACT)
        : FRAMELAB_BG_NONE;
    params.roi = roi;

    Py_BEGIN_ALLOW_THREADS
    status = framelab_compute_roi_metrics(&params, &result);
    Py_END_ALLOW_THREADS

    if (status != FRAMELAB_STATUS_OK) {
        Py_DECREF(image_array);
        Py_XDECREF(background_array);
        return framelab_py_status_error(status, "compute_roi_metrics failed");
    }

    ret = build_roi_metrics_result(&result);
    Py_DECREF(image_array);
    Py_XDECREF(background_array);
    return ret;
}

static PyObject *py_decode_raw_file(PyObject *self, PyObject *args, PyObject *kwargs) {
    static char *kwlist[] = {
        "path",
        "pixel_format",
        "width",
        "height",
        "stride_bytes",
        "offset_bytes",
        NULL
    };
    const char *path = NULL;
    const char *pixel_format_name = NULL;
    unsigned long width = 0UL;
    unsigned long height = 0UL;
    unsigned long stride_bytes = 0UL;
    unsigned long long offset_bytes = 0ULL;
    FramelabPixelFormat pixel_format;
    npy_intp dims[2];
    PyArrayObject *out_array = NULL;
    FramelabRawLoadParams params;
    FramelabStatus status;
    (void)self;

    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "sskk|kK:decode_raw_file",
            kwlist,
            &path,
            &pixel_format_name,
            &width,
            &height,
            &stride_bytes,
            &offset_bytes)) {
        return NULL;
    }
    pixel_format = framelab_pixel_format_from_string(pixel_format_name);
    if (pixel_format == FRAMELAB_PIXFMT_UNKNOWN) {
        PyErr_Format(PyExc_ValueError, "unsupported pixel_format string: %s", pixel_format_name);
        return NULL;
    }
    if (width == 0UL || height == 0UL || width > (unsigned long)INT32_MAX || height > (unsigned long)INT32_MAX) {
        PyErr_SetString(PyExc_ValueError, "width and height must be positive and reasonable");
        return NULL;
    }
    dims[0] = (npy_intp)height;
    dims[1] = (npy_intp)width;
    out_array = (PyArrayObject *)PyArray_SimpleNew(2, dims, NPY_UINT16);
    if (out_array == NULL) {
        return NULL;
    }

    memset(&params, 0, sizeof(params));
    params.path = path;
    params.width = (uint32_t)width;
    params.height = (uint32_t)height;
    params.src_stride_bytes = (uint32_t)stride_bytes;
    params.offset_bytes = (size_t)offset_bytes;
    params.pixel_format = pixel_format;

    Py_BEGIN_ALLOW_THREADS
    status = framelab_load_raw_and_decode(
        &params,
        (uint16_t *)PyArray_DATA(out_array),
        (uint32_t)width
    );
    Py_END_ALLOW_THREADS

    if (status != FRAMELAB_STATUS_OK) {
        Py_DECREF(out_array);
        return framelab_py_status_error(status, "decode_raw_file failed");
    }

    return (PyObject *)out_array;
}

static PyMethodDef framelab_methods[] = {
    {
        "compute_static_metrics",
        (PyCFunction)py_compute_static_metrics,
        METH_VARARGS,
        PyDoc_STR("compute_static_metrics(image) -> (min_non_zero, max_pixel)")
    },
    {
        "compute_dynamic_metrics",
        (PyCFunction)py_compute_dynamic_metrics,
        METH_VARARGS | METH_KEYWORDS,
        PyDoc_STR(
            "compute_dynamic_metrics(image, *, threshold_value, mode, avg_count_value, background=None, clip_negative=True)\n"
            "-> {'sat_count', 'min_non_zero', 'max_pixel', 'avg_topk', 'avg_topk_std', 'avg_topk_sem'}"
        )
    },
    {
        "compute_roi_metrics",
        (PyCFunction)py_compute_roi_metrics,
        METH_VARARGS | METH_KEYWORDS,
        PyDoc_STR(
            "compute_roi_metrics(image, *, roi_rect, background=None, clip_negative=True)\n"
            "-> (roi_max, roi_mean, roi_std, roi_sem)"
        )
    },
    {
        "decode_raw_file",
        (PyCFunction)py_decode_raw_file,
        METH_VARARGS | METH_KEYWORDS,
        PyDoc_STR(
            "decode_raw_file(path, pixel_format, width, height, stride_bytes=0, offset_bytes=0) -> uint16 ndarray"
        )
    },
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef framelab_module = {
    PyModuleDef_HEAD_INIT,
    "_native",
    "FrameLab native backend Python extension.",
    -1,
    framelab_methods,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC PyInit__native(void) {
    PyObject *module = NULL;

    import_array();

    module = PyModule_Create(&framelab_module);
    if (module == NULL) {
        return NULL;
    }

    if (PyModule_AddStringConstant(module, "__version__", "0.3.0") < 0) {
        Py_DECREF(module);
        return NULL;
    }
    return module;
}
